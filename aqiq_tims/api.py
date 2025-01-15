import frappe
from frappe import _

def sales_invoice_on_submit(doc, method):
    """Handle TIMS submission on Sales Invoice submit"""
    
    # Get TIMS settings
    tims_settings = frappe.get_single('TIMS Device Setup')
    
    if not tims_settings.send_invoices_to_kra_on_submit:
        return
        
    if doc.is_return and not tims_settings.send_credit_notes:
        return
        
    # Don't send if already sent
    if doc.custom_sent_to_kra:
        return
        
    try:
        from aqiq_tims.services.rest import send_request
        send_request(doc.name)
        
    except Exception as e:
        frappe.log_error(
            title="Failed to send invoice to TIMS",
            message=frappe.get_traceback()
        )
        if not tims_settings.allow_submission_on_failure:
            frappe.throw(
                _("Failed to send invoice to TIMS: {0}").format(str(e))
            ) 



def sales_invoice_is_return(doc, method=None):
    if doc.is_return:
        for row in doc.items:
            if row.delivery_note:
                return_against_del = frappe.db.get_value("Delivery Note", row.delivery_note, "return_against")
                if return_against_del:
                    sales_doc=frappe.get_all("Sales Invoice Item",{"delivery_note":return_against_del},["parent"],limit=1)
                    if sales_doc:
                        frappe.db.set_value("Sales Invoice",doc.name,"return_against",sales_doc[0]['parent'])
                        # frappe.msgprint(f"Delivery Note {row.delivery_note} is a return against {sales_doc[0]['parent']}.")