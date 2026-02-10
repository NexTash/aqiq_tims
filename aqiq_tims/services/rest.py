import re
import frappe
import json
import requests
from frappe.utils import today
from datetime import datetime
from aqiq_tims.services.qr import generate_qr_code 

@frappe.whitelist()
def send_request(invoice):
    try:
        device_setup = frappe.get_single('TIMS Device Setup')
        doc = frappe.get_doc("Sales Invoice", invoice)
        payload = build_payload(doc, device_setup)
        # return payload

        if device_setup.status == 'Active':
            if is_valid_posting_date(doc, device_setup):
                send_payload(payload, invoice, doc)
                pass
            else:
                frappe.msgprint(
                    msg="Invoice Posting Date Must be Today's Date",
                    title="Error Message",
                    indicator="red",
                )
        else:
            frappe.msgprint(
                msg="TIMS Device Setup for Sending Invoices is not Active.",
                title="Error Message",
                indicator="red",
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
    rct_no = doc.rct_no or doc.name
    customer_pin = frappe.db.get_value("Customer", doc.customer, "tax_id") or ''
    invoice_items = get_invoice_items(doc.name)
    tax_category = get_tax_category(doc)
    
    vat_values = initialize_vat_values()
    items = []

    for item in invoice_items:
        new_item, net_amount, tax_amount, gross_after_discount = calculate_tax(item, tax_category, doc.total)
             
        vat_values = update_vat_values(vat_values, tax_category, net_amount, tax_amount)
        items.append(new_item)

    payload = create_payload(doc, vat_values, items, payment_method, customer_pin, till_no, rct_no)
    return payload


def get_invoice_items(invoice):
    query = """
        SELECT sii.name, sii.item_code, sii.item_name, sii.rate, sii.base_rate, sii.base_amount,
        sii.base_net_rate, sii.base_net_amount, sii.qty, sii.item_tax_template, 
        it_template.title, it_template_detail.tax_rate
        FROM `tabSales Invoice Item` sii
        LEFT JOIN `tabItem Tax Template` it_template ON it_template.name = sii.item_tax_template
        LEFT JOIN `tabItem Tax Template Detail` it_template_detail ON it_template_detail.parent = sii.item_tax_template
        WHERE sii.parent = %s
    """
    return frappe.db.sql(query, invoice, as_dict=True)

def get_tax_category(invoice):


    territory = frappe.db.get_value("Customer",invoice.customer, "territory")

    if territory == "Kenya":
        return "16% VAT"
    else:
        return "Exempt"
    
    # is_inclusive_or_exclusive = frappe.db.get_value('Sales Taxes and Charges', 
    # {'parenttype': 'Sales Invoice', 'parent': invoice}, 
    # 'included_in_print_rate')
    # return "Inclusive" if is_inclusive_or_exclusive == 1 else "Exclusive"


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

def get_exchange_rate(from_currency="USD", to_currency="KES"):
    exchange_rate = frappe.db.get_value(
        "Currency Exchange",
        {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "for_selling": 1
        },
        "exchange_rate",
        order_by="date desc"
    )

    if not exchange_rate:
        frappe.msgprint(
            msg=(
                f"Selling exchange rate ({from_currency} → {to_currency}) "
                "is not defined in Currency Exchange."
            ),
            title="Exchange Rate Missing",
            indicator="red",
        )
        frappe.throw("Missing selling exchange rate")

    return float(exchange_rate)

def calculate_discount(item, total_amount):

    latest_rule_title = frappe.db.get_value(
        "Pricing Rule",
        filters={
            "selling": 1,
        },
        fieldname="title",
        order_by="creation desc"
    )
    
    if not latest_rule_title:
        return 0.0
    
    pricing_rules = frappe.get_all(
        "Pricing Rule",
        filters={
            "title": latest_rule_title,
            "selling": 1,
            "disable": 0,
        },
        fields=["name", "title", "min_amt", "max_amt", "discount_percentage"],
        order_by="min_amt asc"
    )
    
    if not pricing_rules:
        return 0.0
    
    applicable_rule = None
    for rule in pricing_rules:
        min_amt = float(rule.min_amt or 0)
        max_amt = float(rule.max_amt or 0)
        
        if min_amt <= total_amount <= max_amt:
            applicable_rule = rule
            break
    
    if not applicable_rule:
        return 0.0
    
    discount_percentage = float(applicable_rule.discount_percentage or 0)
    
    if discount_percentage == 0:
        return 0.0

    item_rate = float(item.rate or 0)
    qty = float(item.qty or 1.0)
    item_total = item_rate * qty
    
    discount_amount = (item_total * discount_percentage) / 100
    
    return round(discount_amount, 2)



def calculate_tax(item, tax_category, total_amount=0.0):

    if tax_category == "16% VAT":
        tax_rate = 16.0
    else:
        tax_rate = 0.0

    if tax_rate != 16.0:
        exchange_rate = get_today_exchange_rate(from_currency="USD", to_currency="KES")
        base_net_rate = float(item.rate or 0) * exchange_rate
        unit_price = round(base_net_rate, 2)
    else:
        base_net_rate = float(item.rate or 0)
        unit_price = float(item.rate or 0)  

    qty = float(item.qty or 1.0)

  
    
    discount = calculate_discount(item, total_amount)
    
    taxtype = 16 if tax_category == "16% VAT" else 0

    if tax_category == "Exempt":
        hs_code = "0001.12.00"
        product_code = "0001.12.00"
    else:
        hs_code = get_hs_code(item.title)
        if hs_code == "0001.12.00":
            product_code = "0001.12.00"
        else:
            product_code = item.item_code
    
    gross_after_discount = round(unit_price * qty - discount, 2)

    if tax_rate > 0:
        net_amount = round(gross_after_discount / (1 + tax_rate / 100), 2)
        tax_amount = round(gross_after_discount - net_amount, 2)
    else:
        net_amount = gross_after_discount
        tax_amount = 0.0

    new_item = {
        "productCode": product_code,
        "productDesc": item.item_name,
        "quantity": round(qty, 2),
        "unitPrice": round(unit_price, 2),
        "discount": round(discount, 2),
        "taxtype": taxtype,  
    }

    return new_item, net_amount, tax_amount, gross_after_discount


def get_hs_code(tax_type):
    if tax_type == "Exempt":
        return "0001.12.00"
    else:
        return "0022.12.00"
    return "" 

def update_vat_values(vat_values, tax_category, net_amount, tax_amount):
    if tax_category == "16% VAT":
        vat_values["VAT_A_NET"] += net_amount
        vat_values["VAT_A"] += tax_amount
    elif tax_category == "Exempt":
        vat_values["VAT_E_NET"] += net_amount
        vat_values["VAT_E"] += tax_amount
    elif tax_category == "8% VAT":
        vat_values["VAT_B_NET"] += net_amount
        vat_values["VAT_B"] += tax_amount
    elif tax_category == "10% VAT":
        vat_values["VAT_C_NET"] += net_amount
        vat_values["VAT_C"] += tax_amount
    elif tax_category == "2% VAT":
        vat_values["VAT_D_NET"] += net_amount
        vat_values["VAT_D"] += tax_amount
    elif tax_category == "Zero Rated":
        vat_values["VAT_E_NET"] += net_amount
        vat_values["VAT_E"] += tax_amount

    return vat_values

def create_payload(doc, vat_values, items, payment_method, customer_pin, till_no, rct_no):
    payload_type = "sales" if not doc.is_return else "refund"
    cuin = ""
    original_payload_str = ""

    if doc.is_return and doc.return_against:
        cuin, original_payload_str = frappe.db.get_value(
            "KRA Response", 
            {"invoice_number": doc.return_against}, 
            ["cuin", "payload_sent"]
        )

    if payload_type == "refund":
        try:
            submitted_payload = eval(original_payload_str)
        except:
            submitted_payload = json.loads(original_payload_str)
        
        submitted_payload["saleType"] = "refund"
        submitted_payload["cuin"] = cuin
        submitted_payload["rctNo"] = rct_no
        submitted_payload["Payment"] = payment_method
        
        return submitted_payload

    # Calculate final total (Net + Tax from all items)
    final_total = round(
        vat_values["VAT_A_NET"] + vat_values["VAT_A"] +
        vat_values["VAT_B_NET"] + vat_values["VAT_B"] +
        vat_values["VAT_C_NET"] + vat_values["VAT_C"] +
        vat_values["VAT_D_NET"] + vat_values["VAT_D"] +
        vat_values["VAT_E_NET"] + vat_values["VAT_E"] +
        vat_values["VAT_F_NET"] + vat_values["VAT_F"], 2
    )

    payload = {
        "saleType": "sales",
        "cuin": "",
        "till": till_no,
        "rctNo": rct_no,
        "total": round(abs(final_total), 2),
        "Paid": round(abs(final_total), 2),
        "Payment": payment_method,
        "CustomerPIN": customer_pin,
        "VAT_A_Net": round(abs(vat_values["VAT_A_NET"]), 2),
        "VAT_A": round(abs(vat_values["VAT_A"]), 2),
        "VAT_B_Net": round(abs(vat_values["VAT_B_NET"]), 2),
        "VAT_B": round(abs(vat_values["VAT_B"]), 2),
        "VAT_C_Net": round(abs(vat_values["VAT_C_NET"]), 2),
        "VAT_C": round(abs(vat_values["VAT_C"]), 2),
        "VAT_D_Net": round(abs(vat_values["VAT_D_NET"]), 2),
        "VAT_D": round(abs(vat_values["VAT_D"]), 2),
        "VAT_E_Net": round(abs(vat_values["VAT_E_NET"]), 2),
        "VAT_E": round(abs(vat_values["VAT_E"]), 2),
        "VAT_F_Net": round(abs(vat_values["VAT_F_NET"]), 2),
        "VAT_F": round(abs(vat_values["VAT_F"]), 2),
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
        "response_code": data.get("ResponseCode", ""),
        "message": data.get("Message", ""),
        "tin": data.get("TSIN", ""),
        "cusn": data.get("CUSN", ""),
        "cuin": data.get("CUIN", ""),
        "qr_code": data.get("QRCode", ""),
        "signing_time": data.get("dtStmp", ""),
        "invoice_number": invoice,
        "payload_sent": str(payload)
    })

    kra_response.insert(ignore_permissions=True)
    frappe.db.commit()
    
    qr_code = data.get("QRCode", "")

    if data.get('ResponseCode') == '000':
        update_doc_with_response(doc, data, qr_code)
        frappe.msgprint(
            msg="Invoice Successfully Submitted to KRA",
            title='Success',
            indicator='green',
        )
    else:
        frappe.msgprint(
            msg=f"Invoice Submission to KRA Failed. Error: {data.get('Message', 'Unknown error')}. Please Check KRA Response Generated.",
            title='Error Message',
            indicator='red',
        )


def update_doc_with_response(doc, data, qr_code):
    doc.custom_tims_response_code = data.get("ResponseCode", "")
    
    qr_image = generate_qr_code(doc.name, qr_code)

    doc.custom_tsin = data.get("TSIN", "")
    doc.custom_cusn = data.get("CUSN", "")
    doc.cu_invoice_date = data.get("dtStmp", "")
    doc.cu_link = data.get("QRCode", "")
    doc.custom_qr_code = data.get("QRCode", "")
    doc.kra_qr_code = qr_image    
    doc.custom_kra_signing_time = data.get("dtStmp", "")
    doc.etr_serial_number = "KRAMW017202207049581"
    doc.etr_invoice_number = data.get("CUIN", "")
    doc.custom_sent_to_kra = 1
    doc.sent_to_kra = 1
    
    if doc.docstatus == 0:
        doc.save(ignore_permissions=True)
        doc.submit()
    else:
        doc.db_set('custom_tims_response_code', data.get("ResponseCode", ""))
        doc.db_set('custom_tsin', data.get("TSIN", ""))
        doc.db_set('custom_cusn', data.get("CUSN", ""))
        doc.db_set('cu_invoice_date', data.get("dtStmp", ""))
        doc.db_set('cu_link', data.get("QRCode", ""))
        doc.db_set('custom_qr_code', data.get("QRCode", ""))
        doc.db_set('kra_qr_code', qr_image)
        doc.db_set('custom_kra_signing_time', data.get("dtStmp", ""))
        doc.db_set('etr_serial_number', "KRAMW017202207049581")
        doc.db_set('etr_invoice_number', data.get("CUIN", ""))
        doc.db_set('custom_sent_to_kra', 1)
        doc.db_set('sent_to_kra', 1)
        frappe.db.commit()
    
    doc.reload()
    # if doc.docstatus == 0:


def handle_exception(exception):
    error_message = "TIMS KRA Error.\n{}".format(frappe.get_traceback())
    frappe.log_error(error_message, "TIMS KRA Error.")
    frappe.msgprint(
        msg="Something Wrong, Please try again or check the "+"<a style='color: red; font-weight: bold;' href='/app/error-log'>Error Logs</a>",
        title="Error Message",
        indicator='red',
    )
    return exception
