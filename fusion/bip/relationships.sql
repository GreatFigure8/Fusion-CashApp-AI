-- CashAppRelationships: pay-on-behalf relationships between customer accounts.
-- Data set DATA_DS, bind :P_ACCOUNT_NUMBERS (comma-separated account numbers). SELECT only.
-- Row shape is pinned by the Fusion client parser (G_1 rows):
--   ACCOUNT_NUMBER, RELATED_ACCOUNT_NUMBER, RELATED_ACCOUNT_NAME, DIRECTION
-- UNVERIFIED: every table and column name below; confirm on a non-production pod.
WITH requested AS (
  SELECT TRIM(REGEXP_SUBSTR(:P_ACCOUNT_NUMBERS, '[^,]+', 1, LEVEL)) AS account_number
    FROM dual
 CONNECT BY REGEXP_SUBSTR(:P_ACCOUNT_NUMBERS, '[^,]+', 1, LEVEL) IS NOT NULL
),
active_relationships AS (
  SELECT rel.cust_account_id,
         rel.related_cust_account_id
    FROM hz_cust_acct_relate_all rel
   WHERE rel.status = 'A'
     AND rel.bill_to_flag = 'Y'
     AND TRUNC(SYSDATE) BETWEEN NVL(rel.start_date, TRUNC(SYSDATE))
                            AND NVL(rel.end_date, TRUNC(SYSDATE))
)
-- OUTBOUND: the requested account is the CUST_ACCOUNT_ID side.
SELECT queried.account_number         AS account_number,
       related.account_number         AS related_account_number,
       related_party.party_name       AS related_account_name,
       'OUTBOUND'                     AS direction
  FROM active_relationships ar
  JOIN hz_cust_accounts queried ON queried.cust_account_id = ar.cust_account_id
  JOIN hz_cust_accounts related ON related.cust_account_id = ar.related_cust_account_id
  JOIN hz_parties related_party ON related_party.party_id = related.party_id
  JOIN requested req ON req.account_number = queried.account_number
UNION ALL
-- INBOUND: the requested account is the RELATED_CUST_ACCOUNT_ID side.
SELECT queried.account_number         AS account_number,
       related.account_number         AS related_account_number,
       related_party.party_name       AS related_account_name,
       'INBOUND'                      AS direction
  FROM active_relationships ar
  JOIN hz_cust_accounts queried ON queried.cust_account_id = ar.related_cust_account_id
  JOIN hz_cust_accounts related ON related.cust_account_id = ar.cust_account_id
  JOIN hz_parties related_party ON related_party.party_id = related.party_id
  JOIN requested req ON req.account_number = queried.account_number
