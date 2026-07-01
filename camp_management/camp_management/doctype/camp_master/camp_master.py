# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _

class CampMaster(Document):
    def validate(self):
        """
        Triggered before the document is saved.
        """
        self.calculate_occupancy_metrics()
        self.trigger_occupancy_alerts()

    def calculate_occupancy_metrics(self):
        """
        Calculates total capacity, occupied beds, vacant beds, and occupancy %
        from the camp's linked blocks, rooms, and bed records.
        """
        block_names = frappe.get_all(
            "Block Master",
            filters={"camp": self.name},
            pluck="name",
        )

        if block_names:
            room_names = frappe.get_all(
                "Room Master",
                filters={"block": ["in", block_names]},
                pluck="name",
            )

            if room_names:
                self.total_capacity = frappe.db.count("Bed Master", {"room": ["in", room_names]}) or 0
                self.occupied_beds = frappe.db.count(
                    "Bed Master",
                    {"room": ["in", room_names], "status": "Occupied"},
                ) or 0
            else:
                self.total_capacity = 0
                self.occupied_beds = 0
        else:
            self.total_capacity = 0
            self.occupied_beds = 0

        self.vacant_beds = max(0, self.total_capacity - self.occupied_beds)

        if self.total_capacity > 0:
            self.occupancy_percent = (self.occupied_beds / self.total_capacity) * 100
        else:
            self.occupancy_percent = 0.0

    def trigger_occupancy_alerts(self):
        """
        Triggers alerts to the Camp Manager if thresholds are breached (FR-CM-06 / FR-OC-04).
        """
        if not self.camp_manager:
            return

        # Fetch manager's email from the linked Employee record
        manager_email = frappe.db.get_value("Employee", self.camp_manager, "company_email") or \
                        frappe.db.get_value("Employee", self.camp_manager, "personal_email")
        
        if not manager_email:
            return

        alerts = []

        # FR-CM-06: Occupancy Alert Threshold Exceeded
        if self.occupancy_alert_threshold and self.occupancy_percent >= self.occupancy_alert_threshold:
            alerts.append(
                f"<li><b>Occupancy Alert:</b> Current occupancy is at <b>{self.occupancy_percent:.1f}%</b>, meeting or exceeding the threshold of {self.occupancy_alert_threshold}%.</li>"
            )

        # FR-OC-04: Minimum Vacancy Buffer Breached
        if self.minimum_vacancy_buffer and self.vacant_beds <= self.minimum_vacancy_buffer:
            alerts.append(
                f"<li><b>Vacancy Alert:</b> Available vacant beds have dropped to <b>{self.vacant_beds}</b>, which is at or below the minimum buffer of {self.minimum_vacancy_buffer}.</li>"
            )

        # Dispatch email if there are active alerts
        if alerts:
            message = f"""
            <p>Dear Camp Manager,</p>
            <p>Please note the following capacity alerts for <b>{self.camp_name}</b>:</p>
            <ul>
                {''.join(alerts)}
            </ul>
            <p>Please review your room allocations and take necessary actions.</p>
            """
            
            frappe.sendmail(
                recipients=[manager_email],
                subject=_(f"Capacity Alert: {self.camp_name}"),
                message=message,
                now=False # Enqueues the email in the background to prevent slowing down the 'Save' action
            )
