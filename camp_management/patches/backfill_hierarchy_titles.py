import frappe


def execute():
	"""
	Populate the newly added block_title/room_title/bed_title fields for records that
	existed before these fields were introduced. Parents are backfilled before children
	since each title is built from its parent's title. Uses frappe.db.set_value directly
	(not doc.save()) to avoid the Block/Room -> Camp Master cascade save and its email
	alerts, since this is a plain data backfill.
	"""
	for block in frappe.get_all("Block Master", fields=["name", "camp", "block_name"]):
		camp_name = frappe.db.get_value("Camp Master", block.camp, "camp_name") if block.camp else None
		title = f"{camp_name} / {block.block_name}" if camp_name and block.block_name else block.block_name
		frappe.db.set_value("Block Master", block.name, "block_title", title, update_modified=False)

	for room in frappe.get_all("Room Master", fields=["name", "block", "room_number"]):
		block_title = frappe.db.get_value("Block Master", room.block, "block_title") if room.block else None
		title = (
			f"{block_title} / Room {room.room_number}"
			if block_title and room.room_number
			else room.room_number
		)
		frappe.db.set_value("Room Master", room.name, "room_title", title, update_modified=False)

	for bed in frappe.get_all("Bed Master", fields=["name", "room", "bed_number"]):
		room_title = frappe.db.get_value("Room Master", bed.room, "room_title") if bed.room else None
		title = f"{room_title} / Bed {bed.bed_number}" if room_title and bed.bed_number else bed.bed_number
		frappe.db.set_value("Bed Master", bed.name, "bed_title", title, update_modified=False)
