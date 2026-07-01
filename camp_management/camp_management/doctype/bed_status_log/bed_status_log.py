# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _

class BedStatusLog(Document):
    def validate(self):
        """
        Enforces complete immutability at the controller level.
        Prevents any manual creation or modification through user forms, 
        Data Import, or standard REST API endpoints.
        """
        # Checks flags that are only present during automated system execution
        if not self.flags.ignore_permissions:
            frappe.throw(
                _("Bed Status Log records are system-generated audit trails and cannot be manually created or edited."),
                frappe.PermissionError
            )

    def before_insert(self):
        """
        Ensures convenience values are automatically populated and accurate before writing to DB.
        """
        if self.bed and not self.room:
            # Auto-fetch the convenience field 'room' directly from the target Bed Master
            self.room = frappe.db.get_value("Bed Master", self.bed, "room")
            
        # Ensure tracking context fields default correctly if omitted
        if not self.changed_on:
            self.changed_on = frappe.utils.now_datetime()
        if not self.changed_by:
            self.changed_by = frappe.session.user