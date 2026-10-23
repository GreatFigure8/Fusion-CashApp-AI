-- CashAppReceiptSignals: receipts joined to their bank statement lines, for receipt matching.
-- Data set DATA_DS, binds :P_DATE_FROM and :P_DATE_TO (YYYY-MM-DD, on the receipt date).
-- SELECT only. One G_1 row per receipt x matched statement line; statement columns are null for
-- an unreconciled receipt. The payer bank account is exposed only as a SHA-256 hash.
-- UNVERIFIED: every table and column name below, including the reconciliation link table;
-- confirm on a non-production pod before use.
SELECT acr.cash_receipt_id                           AS cash_receipt_id,
       acr.receipt_number                            AS receipt_number,
       acr.receipt_date                              AS receipt_date,
       acr.creation_date                             AS creation_date,
       acr.amount                                    AS amount,
       acr.currency_code                             AS currency_code,
       cust.account_number                           AS customer_account_number,
       acr.comments                                  AS receipt_comments,
       csl.statement_line_id                         AS statement_line_id,
       csl.customer_reference                        AS statement_line_reference,
       csl.addenda_text                              AS statement_line_addenda,
       csl.contact_name                              AS statement_payer_name,
       STANDARD_HASH(ieba.bank_account_num, 'SHA256') AS payer_bank_account_hash
  FROM ar_cash_receipts_all acr
  LEFT JOIN hz_cust_accounts cust
         ON cust.cust_account_id = acr.pay_from_customer
  LEFT JOIN ce_statement_reconcils_all csr
         ON csr.reference_id = acr.cash_receipt_id
        AND csr.reference_type = 'RECEIPT'
        AND csr.status_flag = 'M'
  LEFT JOIN ce_statement_lines csl
         ON csl.statement_line_id = csr.statement_line_id
  LEFT JOIN ce_statement_headers csh
         ON csh.statement_header_id = csl.statement_header_id
  LEFT JOIN iby_ext_bank_accounts ieba
         ON ieba.ext_bank_account_id = acr.customer_bank_account_id
 WHERE acr.receipt_date BETWEEN TO_DATE(:P_DATE_FROM, 'YYYY-MM-DD')
                            AND TO_DATE(:P_DATE_TO, 'YYYY-MM-DD')
