import frappe
import json
import requests
from frappe.utils import today
from datetime import datetime

@frappe.whitelist()
def send_request(invoice):
    try:
        device_setup = frappe.get_single('TIMS Device Setup')
        doc = frappe.get_doc("Sales Invoice", invoice)

        if device_setup.status == 'Active':
            if is_valid_posting_date(doc, device_setup):
                payload = build_payload(doc, device_setup)
                send_payload(payload, invoice, doc)
            else:
                frappe.msgprint(
                    msg="Invoice Posting Date Must be Today's Date",
                    title='Error Message',
                    indicator='red',
                )
        else:
            frappe.msgprint(
                msg='TIMS Device Setup for Sending Invoices is not Active.',
                title='Error Message',
                indicator='red',
            )
    except Exception as e:
        handle_exception(e)


def is_valid_posting_date(doc, device_setup):
    today = datetime.now().strftime("%d-%m-%Y")
    posting_date = doc.posting_date.strftime("%d-%m-%Y")
    return posting_date == today or device_setup.allow_other_day_posting


def build_payload(doc, device_setup):
    payment_method = "Cash" if doc.status == 'Paid' else 'Credit'
    till_no = ''
    rct_no = doc.name
    customer_pin = frappe.db.get_value("Customer", doc.customer, "tax_id") or ''
    invoice_items = get_invoice_items(doc.name)
    tax_category = get_tax_category(doc.name)
    
    vat_values = initialize_vat_values()
    items = []

    for item in invoice_items:
        new_item, taxable_amount, tax_amount = calculate_tax(item, tax_category)
        vat_values = update_vat_values(vat_values, item.title, taxable_amount, tax_amount)
        items.append(new_item)

    payload = create_payload(doc, vat_values, items, payment_method, customer_pin, till_no, rct_no)
    return payload


def get_invoice_items(invoice):
    query = """
        SELECT DISTINCT sii.name, sii.item_code, sii.item_name, sii.rate, sii.base_rate, sii.base_amount,
        sii.base_net_rate, sii.base_net_amount, sii.qty, sii.item_tax_template, 
        item_tax.item_tax_template, it_template.title, it_template_detail.tax_rate
        FROM `tabSales Invoice Item` sii
        LEFT JOIN `tabItem Tax` item_tax ON item_tax.parent = sii.item_code 
        LEFT JOIN `tabItem Tax Template` it_template ON it_template.name = item_tax.item_tax_template
        LEFT JOIN `tabItem Tax Template Detail` it_template_detail ON it_template_detail.parent = item_tax.item_tax_template
        WHERE sii.parent = %s
    """
    return frappe.db.sql(query, invoice, as_dict=True)


def get_tax_category(invoice):
    is_inclusive_or_exclusive = frappe.db.get_value('Sales Taxes and Charges', {'parenttype': 'Sales Invoice', 'parent': invoice}, 'included_in_print_rate')
    return "Inclusive" if is_inclusive_or_exclusive == 1 else "Exclusive"


def initialize_vat_values():
    return {
        "VAT_A_NET": 0,
        "VAT_A": 0,
        "VAT_B_NET": 0,
        "VAT_B": 0,
        "VAT_C_NET": 0,
        "VAT_C": 0,
        "VAT_D_NET": 0,
        "VAT_D": 0,
        "VAT_E_NET": 0,
        "VAT_E": 0,
        "VAT_F_NET": 0,
        "VAT_F": 0,
    }


def calculate_tax(item, tax_category):
    tax_rate = float(item.tax_rate or 0)
    tax_value = 1 + (tax_rate / 100)
    
    qty = float(item.qty or 1.0)
    
    base_net_rate = float(item.base_net_rate or 0)

    unit_price = round(base_net_rate, 2)
    discount = 0.0
    
    hs_code = get_hs_code(item.title)
    if hs_code == "0043.11.00":
        product_code = "0043.11.00"
    elif hs_code == "0022.10.00":
        product_code = "0022.10.00"
    else:
        product_code = item.item_code

    new_item = {
        "productCode": product_code,
        "productDesc": item.item_name,
        "quantity": abs(float(qty)),
        "unitPrice": abs(float(unit_price)),
        "discount": abs(float(discount)),
        "taxtype": int(tax_rate),
        # "hsCode": hs_code
    }

    if tax_category == "Inclusive":
        taxable_amount = (unit_price * qty - discount) / tax_value
    else:
        taxable_amount = unit_price * qty - discount
        
    tax_amount = taxable_amount * (tax_rate / 100)

    return new_item, taxable_amount, tax_amount


def get_hs_code(tax_type):
    """
    Returns the appropriate HS code based on tax type
    """
    # frappe.throw(f"{tax_type}")
    if tax_type == "Exempt":
        return "0043.11.00"
    elif tax_type == "Zero Rated":
        return "0022.10.00"
    return ""  # Return empty string for other tax types


def update_vat_values(vat_values, tax_type, taxable_amount, tax_amount):
    if tax_type == "VAT 16%":
        vat_values["VAT_A_NET"] += taxable_amount
        vat_values["VAT_A"] += tax_amount
    elif tax_type == "VAT 8%":
        vat_values["VAT_B_NET"] += taxable_amount
        vat_values["VAT_B"] += tax_amount
    elif tax_type == "VAT 10%":
        vat_values["VAT_C_NET"] += taxable_amount
        vat_values["VAT_C"] += tax_amount
    elif tax_type == "VAT 2%":
        vat_values["VAT_D_NET"] += taxable_amount
        vat_values["VAT_D"] += tax_amount
    elif tax_type == "Zero Rated":
        vat_values["VAT_E_NET"] += taxable_amount
        vat_values["VAT_E"] += tax_amount
    elif tax_type == "Exempt":
        vat_values["VAT_F_NET"] += taxable_amount
        vat_values["VAT_F"] += tax_amount

    return vat_values


def create_payload(doc, vat_values, items, payment_method, customer_pin, till_no, rct_no):
    total = sum([
        vat_values["VAT_A_NET"] + vat_values["VAT_A"],
        vat_values["VAT_B_NET"] + vat_values["VAT_B"],
        vat_values["VAT_C_NET"] + vat_values["VAT_C"],
        vat_values["VAT_D_NET"] + vat_values["VAT_D"],
        vat_values["VAT_E_NET"],
        vat_values["VAT_F_NET"]
    ])

    payload_type = "sales" if not doc.is_return else "refund"
    cuin = "" if not doc.is_return else frappe.db.get_value("KRA Response", {"invoice_number": doc.return_against}, "cuin")

    payload = {
        "saleType": payload_type,
        "cuin": cuin,
        "till": till_no,
        "rctNo": rct_no,
        "total": round(abs(float(total)), 2),
        "Paid": round(abs(float(total)), 2),
        "Payment": payment_method,
        "CustomerPIN": customer_pin,
        "VAT_A_Net": round(abs(float(vat_values["VAT_A_NET"])), 2),
        "VAT_A": round(abs(float(vat_values["VAT_A"])), 2),
        "VAT_B_Net": round(abs(float(vat_values["VAT_B_NET"])), 2),
        "VAT_B": round(abs(float(vat_values["VAT_B"])), 2),
        "VAT_C_Net": round(abs(float(vat_values["VAT_C_NET"])), 2),
        "VAT_C": round(abs(float(vat_values["VAT_C"])), 2),
        "VAT_D_Net": round(abs(float(vat_values["VAT_D_NET"])), 2),
        "VAT_D": round(abs(float(vat_values["VAT_D"])), 2),
        "VAT_E_Net": round(abs(float(vat_values["VAT_E_NET"])), 2),
        "VAT_E": round(abs(float(vat_values["VAT_E"])), 2),
        "VAT_F_Net": round(abs(float(vat_values["VAT_F_NET"])), 2),
        "VAT_F": round(abs(float(vat_values["VAT_F"])), 2),
        "data": items
    }

    return payload


def send_payload(payload, invoice, doc):
    try:
        device_setup = frappe.get_single('TIMS Device Setup')
        response = requests.post(
            f"http://{device_setup.ip}:{device_setup.port}/api/values/PostTims",
            json=payload,
            timeout=60
        )
        handle_response(response, invoice, doc, payload)
    except Exception as e:
        frappe.msgprint(
            msg="Request Time Out Error, please make sure the TIMS/ETR Machine is active.",
            title="Error Message",
            indicator='red',
        )


def handle_response(response, invoice, doc, payload):
    data = json.loads(response.text)

    kra_response = frappe.get_doc({
        "doctype": "KRA Response",
        "response_code": data["ResponseCode"] or '',
        "message": data["Message"],
        "tin": data["TSIN"],
        "cusn": data["CUSN"],
        "cuin": data["CUIN"],
        "qr_code": data["QRCode"],
        "signing_time": data["dtStmp"],
        "invoice_number": invoice,
        "payload_sent": str(payload)
    })

    kra_response.insert()
    frappe.db.commit()

    if data['ResponseCode'] == '000':
        update_doc_with_response(doc, data)
    else:
        frappe.msgprint(
            msg="Invoice Submission to KRA Failed. Please Check KRA Response Generated.",
            title='Error Message',
            indicator='red',
        )


def update_doc_with_response(doc, data):
    doc.custom_tims_response_code = data["ResponseCode"]
    doc.custom_tsin = data["TSIN"]
    doc.custom_cusn = data["CUSN"]
    doc.custom__cuin = data["CUIN"]
    doc.cu_invoice_date = data["dtStmp"]
    doc.cu_link = data["QRCode"]
    doc.custom_qr_code = data["QRCode"]
    doc.custom_qr_image = data["QRCode"]
    doc.custom_kra_signing_time = data["dtStmp"]
    doc.etr_serial_number = "KRAMW017202207049144"
    doc.etr_invoice_number = data["CUIN"]
    doc.custom_sent_to_kra = 1
    doc.save(ignore_permissions=True)

    if doc.docstatus == 0:
        doc.submit()
        doc.reload()


def handle_exception(exception):
    error_message = "TIMS KRA Error.\n{}".format(frappe.get_traceback())
    frappe.log_error(error_message, "TIMS KRA Error.")
    frappe.msgprint(
        msg="Something Wrong, Please try again or check the "+"<a style='color: red; font-weight: bold;' href='/app/error-log'>Error Logs</a>",
        title="Error Message",
        indicator='red',
    )
    return exception
