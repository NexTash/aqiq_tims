# -*- coding: utf-8 -*-
import frappe
import requests
import base64
from io import BytesIO

@frappe.whitelist()
def generate_qr_code(field_value):
    """
    Generate a QR code using a free API and return base64 image.
    """
    if not field_value:
        frappe.throw("QR Code data cannot be empty")

    try:
        api_url = "https://api.qrserver.com/v1/create-qr-code/"
        params = {
            "data": field_value,
            "size": "200x200"  
        }
        response = requests.get(api_url, params=params)

        if response.status_code == 200:
            b64_str = base64.b64encode(response.content).decode("utf-8")
            return "data:image/png;base64," + b64_str
        else:
            frappe.throw(f"Failed to generate QR code. API response: {response.status_code}")

    except Exception as e:
        frappe.log_error(f"QR Code API Error: {str(e)}")
        frappe.throw(f"Failed to generate QR code: {str(e)}")
