# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff, now_datetime, today


class RoomAllocation(Document):
	def validate(self):
		"""
		Runs calculations and validation logic before saving/submitting.
		"""
		self.calculate_duration()
		self.fetch_department_fallback()
		self.auto_activate_on_submit()
		self.validate_bed_availability()
		self.validate_single_active_allocation()

	def on_submit(self):
		"""
		Triggered when the Allocation is submitted (Approved/Activated).
		Locks the bed and updates its reference points.
		"""
		if self.allocation_status == "Active":
			self.lock_bed()
			self.update_employee_accommodation()

	def on_cancel(self):
		"""
		Triggered when an active or approved allocation is cancelled.
		Releases the bed.
		"""
		self.release_bed(status_on_release="Available", description=f"Allocation cancelled via {self.name}")
		self.update_employee_accommodation(clear=True)

	def calculate_duration(self):
		"""
		Calculates the duration in days using:
		Actual Check-Out Date (if available) or Expected Check-Out Date - Check-In Date.
		"""
		start_date = self.check_in_date or today()
		end_date = self.actual_check_out_date or self.expected_check_out_date

		if end_date:
			if end_date < start_date:
				frappe.throw(_("Check-Out Date cannot be earlier than the Check-In Date."))
			self.duration_days = date_diff(end_date, start_date)
		else:
			self.duration_days = 0

	def fetch_department_fallback(self):
		"""
		FR-AL-07: Automatically fetches the default Department from the linked Employee profile,
		allowing manual override if already provided.
		"""
		if self.employee and not self.department:
			self.department = frappe.db.get_value("Employee", self.employee, "department")

	def auto_activate_on_submit(self):
		"""
		Native Submit doesn't go through the optional approval workflow (its actions only
		appear for users holding the exact workflow role), so submission must be
		self-sufficient: promote a Draft/Pending Approval allocation to Active whenever it
		actually reaches docstatus 1, instead of relying on the workflow to have set it.
		"""
		if self.docstatus == 1 and self.allocation_status in ("Draft", "Pending Approval"):
			self.allocation_status = "Active"

	def get_target_beds(self):
		"""
		Returns the list of beds this allocation locks/releases: just the selected Bed,
		or every bed in the Room when Allocate Full Room is checked.
		"""
		if self.allocate_full_room and self.room:
			return frappe.get_all("Bed Master", filters={"room": self.room}, pluck="name")
		return [self.bed] if self.bed else []

	def validate_bed_availability(self):
		"""
		FR-AL-02: Validates that the targeted Bed(s) are 'Available' prior to submission.
		Also blocks double-booking by confirming no other document currently retains a lock on it.
		When Allocate Full Room is checked, every bed in the room must be available.
		"""
		for bed in self.get_target_beds():
			bed_status, locked_by = frappe.db.get_value("Bed Master", bed, ["status", "current_allocation"])

			# We only strictly block it if it's not already locked by *this* ongoing allocation
			if bed_status != "Available" and locked_by != self.name:
				frappe.throw(
					_(
						"Bed {0} is currently {1} and cannot be selected. It is locked by transaction {2}."
					).format(
						frappe.bold(bed), frappe.bold(bed_status), frappe.bold(locked_by or _("Unknown"))
					)
				)

	def validate_single_active_allocation(self):
		"""
		FR-AL-XX: An employee may hold at most one 'Active' Room Allocation at a time.
		Room Transfer already checks the source out (via a direct DB update) before the
		new allocation is submitted, so this does not conflict with that flow - it only
		catches the case of two allocations being made Active independently of Room Transfer.
		"""
		if self.allocation_status != "Active" or not self.employee:
			return

		existing = frappe.db.get_value(
			"Room Allocation",
			{
				"employee": self.employee,
				"allocation_status": "Active",
				"docstatus": 1,
				"name": ["!=", self.name or ""],
			},
		)
		if existing:
			frappe.throw(
				_(
					"Employee {0} already has an active allocation ({1}). Only one active allocation is allowed per employee - check it out or transfer it first."
				).format(frappe.bold(self.employee), frappe.bold(existing))
			)

	def lock_bed(self):
		"""
		Performs the transactional lock on the Bed Master record(s) - every bed in the room
		when Allocate Full Room is checked, otherwise just the selected Bed - and flags an
		audit history record into the Bed Status Log for each.
		"""
		for bed in self.get_target_beds():
			previous_status = frappe.db.get_value("Bed Master", bed, "status")

			# Core Update: Flip status to Occupied, tie occupant and transaction links
			frappe.db.set_value(
				"Bed Master",
				bed,
				{"status": "Occupied", "current_occupant": self.employee, "current_allocation": self.name},
			)

			# Generate Immutable History Log Entry
			self.log_bed_status_change(
				bed=bed,
				prev_status=previous_status,
				new_status="Occupied",
				remarks=f"Employee checked in via {self.name}",
			)

		# Trigger hierarchy rollup totals recalculation
		self.update_hierarchy()

	def release_bed(self, status_on_release="Available", description=None):
		"""
		FR-AL-04: Clears occupant details and releases the bed lock(s).
		"""
		for bed in self.get_target_beds():
			previous_status = frappe.db.get_value("Bed Master", bed, "status")

			frappe.db.set_value(
				"Bed Master",
				bed,
				{"status": status_on_release, "current_occupant": None, "current_allocation": None},
			)

			self.log_bed_status_change(
				bed=bed,
				prev_status=previous_status,
				new_status=status_on_release,
				remarks=description or f"Checked out via {self.name}",
			)

		self.update_hierarchy()

	def log_bed_status_change(self, bed, prev_status, new_status, remarks):
		"""
		System-generates a clean, read-only tracking footstep row inside DocType 8 (Bed Status Log).
		"""
		log = frappe.get_doc(
			{
				"doctype": "Bed Status Log",
				"bed": bed,
				"room": self.room,
				"previous_status": prev_status,
				"new_status": new_status,
				"changed_on": now_datetime(),
				"changed_by": frappe.session.user,
				"reference_doctype": self.doctype,
				"reference_name": self.name,
				"remarks": remarks,
			}
		)
		log.insert(ignore_permissions=True)

	def update_hierarchy(self):
		"""
		Cascades total count changes upward through Rooms, Blocks, and Camps.
		"""
		if self.room:
			# Dynamically import helper from bed master script file to prevent code replication
			from camp_management.camp_management.doctype.bed_master.bed_master import update_hierarchy_metrics

			update_hierarchy_metrics(self.room)

	def on_update_after_submit(self):
		"""
		Fires when a submitted document is re-saved with its docstatus staying at 1 -
		this is the hook Frappe actually calls for the Active -> Checked-Out workflow
		transition, since both states are docstatus 1 (on_update is only called for
		docstatus 0 -> 0 saves, so it never sees this transition).
		"""
		if self.allocation_status == "Checked-Out":
			# Use direct DB sets to avoid triggering validation locks on submitted documents
			previous_status = frappe.db.get_value("Bed Master", self.bed, "status")
			if previous_status == "Occupied":
				self.release_bed(
					status_on_release="Available",
					description=f"Employee checked out via workflow action in {self.name}",
				)
				self.update_employee_accommodation(clear=True)

	def update_employee_accommodation(self, clear=False):
		"""
		FR-AL-10 / FR-INT-02: Mirrors this allocation onto the Employee's
		current_accommodation and monthly_accommodation_charge fields, since
		those are read-only and system-maintained (Payroll reads the charge
		directly, so it must never drift from the active allocation's room rate).
		"""
		if not self.employee:
			return

		if clear:
			# Only clear if this is still the allocation the Employee points to,
			# so cancelling a stale/superseded allocation can't wipe out a newer one.
			linked_allocation = frappe.db.get_value("Employee", self.employee, "custom_current_accommodation")
			if linked_allocation != self.name:
				return
			frappe.db.set_value(
				"Employee",
				self.employee,
				{
					"custom_current_accommodation": None,
					"custom_monthly_accommodation_charge": 0,
				},
			)
		else:
			monthly_rent = frappe.db.get_value("Room Master", self.room, "monthly_rent") if self.room else 0
			frappe.db.set_value(
				"Employee",
				self.employee,
				{
					"custom_current_accommodation": self.name,
					"custom_monthly_accommodation_charge": monthly_rent or 0,
				},
			)
