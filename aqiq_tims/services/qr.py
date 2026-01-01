import frappe
import requests
import base64

@frappe.whitelist()
def generate_qr_code(docname, field_value):
    """
    Generate QR code, save as File in Frappe, attach to Sales Invoice,
    and return the URL for 'kra_qr_code'.
    """
    if not field_value:
        frappe.throw("QR Code data cannot be empty")

    try:
        api_url = "https://api.qrserver.com/v1/create-qr-code/"
        params = {"data": field_value, "size": "200x200"}
        response = requests.get(api_url, params=params)

        if response.status_code != 200:
            frappe.throw(f"Failed to generate QR code. API response: {response.status_code}")

        b64_str = base64.b64encode(response.content).decode("utf-8")

        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": f"QR_{docname}.png",
            "attached_to_doctype": "Sales Invoice",
            "attached_to_name": docname,
            "content": b64_str,
            "decode": True,
            "is_private": 0
        })
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return file_doc.file_url

    except Exception as e:
        frappe.log_error(f"QR Code generation error: {str(e)}")
        frappe.throw(f"Failed to generate QR code: {str(e)}")
