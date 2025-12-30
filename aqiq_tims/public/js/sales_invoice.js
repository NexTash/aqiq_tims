frappe.ui.form.on("Sales Invoice", {
  refresh: function (frm) {
    // Only show button if invoice is submitted and not already sent to KRA
    if (frm.doc.docstatus === 1 && !frm.doc.custom_sent_to_kra) {
      frm.add_custom_button(__("Send to TIMS"), function () {
        send_to_tims(frm);
      });
    }
frm.add_custom_button(__("Generate QR"), function () {
    frappe.call({
        method: "aqiq_tims.services.qr.generate_qr_code",
        args: {
            field_value: frm.doc.custom_qr_code // the field containing your URL
        },
        freeze: true,
        freeze_message: __("Generating QR Code..."),
        callback: function (r) {
            if (r.message) {
                // Show QR code in popup
                frappe.msgprint({
                    title: __("Generated QR Code"),
                    message: `<div style="text-align: center;">
                        <img src="${r.message}" alt="QR Code" style="max-width: 300px; width: 100%;" />
                        <p>Scan this QR to open the URL</p>
                    </div>`,
                    wide: 1,
                });
            }
        },
    });
});


    // Show TIMS status in the dashboard
    if (frm.doc.custom_sent_to_kra) {
      var status_color =
        frm.doc.custom_tims_response_code === 0 ? "green" : "red";
      var status_message =
        frm.doc.custom_tims_response_code === 0
          ? "Successfully sent to TIMS"
          : "Failed to send to TIMS";

      frm.dashboard.add_indicator(
        __("TIMS Status: {0}", [status_message]),
        status_color
      );

      // Show TIMS details section
      show_tims_details(frm);
    }
  },

  on_submit: function (frm) {
    frappe.db.get_value(
      "TIMS Device Setup",
      "TIMS Device Setup",
      "send_invoices_to_kra_on_submit",
      function (r) {
        if (r && r.send_invoices_to_kra_on_submit) {
          frm.reload_doc();
        }
      }
    );
  },
});

function send_to_tims(frm) {
  frappe.call({
    method: "aqiq_tims.services.rest.send_request",
    args: {
      invoice: frm.doc.name,
    },
    freeze: true,
    freeze_message: __("Sending to TIMS..."),
    callback: function (r) {
      frm.reload_doc();
    },
  });
}

function show_tims_details(frm) {
  if (frm.doc.custom_sent_to_kra) {
    var html = `
            <div class="tims-details" style="padding: 10px; margin-top: 10px;">
                <div class="row">
                    <div class="col-sm-6">
                        <strong>TIMS Response Code:</strong> ${
                          frm.doc.custom_tims_response_code || ""
                        }
                    </div>
                    <div class="col-sm-6">
                        <strong>Signing Time:</strong> ${
                          frm.doc.custom_kra_signing_time || ""
                        }
                    </div>
                </div>
                <div class="row" style="margin-top: 10px;">
                    <div class="col-sm-4">
                        <strong>TSIN:</strong> ${frm.doc.custom_tsin || ""}
                    </div>
                    <div class="col-sm-4">
                        <strong>CUSN:</strong> ${frm.doc.custom_cusn || ""}
                    </div>
                    <div class="col-sm-4">
                        <strong>CUIN:</strong> ${frm.doc.custom_cuin || ""}
                    </div>
                </div>
                ${
                  frm.doc.custom_kra_qr_code_data
                    ? `
                <div class="row" style="margin-top: 10px;">
                    <div class="col-sm-12">
                        <strong>QR Code Data:</strong>
                        <div style="word-break: break-all; margin-top: 5px;">
                            ${frm.doc.custom_kra_qr_code_data}
                        </div>
                    </div>
                </div>
                `
                    : ""
                }
            </div>
        `;

    $(frm.dashboard.wrapper).find(".tims-details").remove();
    $(frm.dashboard.wrapper).append(html);
  }
}




