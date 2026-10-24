locals {
  environment = "prod"
  schema_name = "CASHAPP_PROD"

  secret_ids = merge(module.vault.secret_ids, { "atp-dsn" = module.atp.connect_string_secret_id })
  vault_ref  = { for name, id in local.secret_ids : name => "vault:${id}" }

  # Environment for the api and every worker: the bootstrap set only (CASHAPP_ prefix, __
  # nesting). Every other setting is a DB config key edited in Settings; see
  # docs/reference/settings.md. Secret leaves are vault:<secret-ocid> references.
  api_env = {
    CASHAPP_ENV             = local.environment
    CASHAPP_ATP__DSN        = local.vault_ref["atp-dsn"]
    CASHAPP_ATP__USER       = local.schema_name
    CASHAPP_ATP__PASSWORD   = local.vault_ref["atp-app-password"]
    CASHAPP_SECRETS__SOURCE = "vault"
  }

  # The removed deploy variables, with the values they always had. Only the release migration
  # container receives them (output migration_env): the s48 data migration seeds the DB config
  # keys from them. Once every environment has applied s48 this local can be emptied.
  settings_seed_env = merge(
    {
      CASHAPP_OBJECT_STORAGE__NAMESPACE               = module.object_storage.namespace
      CASHAPP_OBJECT_STORAGE__BUCKET                  = module.object_storage.bucket_name
      CASHAPP_ANTHROPIC__API_KEY                      = local.vault_ref["anthropic-api-key"]
      CASHAPP_OCI_GENAI__COMPARTMENT_OCID             = var.compartment_ocid
      CASHAPP_OCI_GENAI__DEDICATED_ENDPOINT_OCID      = module.genai.endpoint_id
      CASHAPP_OCI_GENAI__DEDICATED_CLUSTER_OCID       = module.genai.cluster_id
      CASHAPP_IDENTITY__ISSUER                        = var.identity.issuer
      CASHAPP_IDENTITY__JWKS_URL                      = var.identity.jwks_url
      CASHAPP_IDENTITY__AUDIENCE                      = var.identity.audience
      CASHAPP_FUSION__DEFAULT_POD                     = var.fusion_default_pod
      CASHAPP_FUSION__WRITE_ENABLED                   = tostring(var.fusion_write_enabled)
      CASHAPP_FUSION__RELATIONSHIPS_REPORT_PATH       = var.fusion_relationships_report_path
      CASHAPP_INTAKE__DROP_FOLDER                     = var.drop_folder
      CASHAPP_OBSERVABILITY__OCI_MONITORING_NAMESPACE = "cashapp"
    },
    merge([
      for pod, cfg in var.fusion_pods : {
        "CASHAPP_FUSION__PODS__${upper(pod)}__BASE_URL"      = cfg.base_url
        "CASHAPP_FUSION__PODS__${upper(pod)}__USERNAME"      = cfg.username
        "CASHAPP_FUSION__PODS__${upper(pod)}__IS_PRODUCTION" = tostring(cfg.is_production)
        "CASHAPP_FUSION__PODS__${upper(pod)}__PASSWORD"      = local.vault_ref["fusion-${pod}-password"]
      }
    ]...),
    var.smtp == null ? {} : {
      CASHAPP_SMTP__HOST         = var.smtp.host
      CASHAPP_SMTP__PORT         = tostring(var.smtp.port)
      CASHAPP_SMTP__USERNAME     = var.smtp.username
      CASHAPP_SMTP__PASSWORD     = local.vault_ref["smtp-password"]
      CASHAPP_SMTP__FROM_ADDRESS = var.smtp.from_address
    },
  )

  # The web container reads plain values. The two secrets are passed as Vault OCIDs and resolved
  # by the image entrypoint through the resource principal before the server starts.
  web_env = {
    OIDC_ISSUER                   = var.identity.issuer
    OIDC_CLIENT_ID                = var.identity.oidc_client_id
    API_BASE_URL                  = "https://${var.api_hostname}"
    APP_BASE_URL                  = "https://${var.web_hostname}"
    OIDC_CLIENT_SECRET_VAULT_OCID = local.secret_ids["oidc-client-secret"]
    SESSION_SECRET_VAULT_OCID     = local.secret_ids["session-secret"]
  }
}

check "region_is_ashburn" {
  assert {
    condition     = var.region == "us-ashburn-1"
    error_message = "Hosting is Ashburn only: region must be us-ashburn-1."
  }
}

module "network" {
  source = "../../modules/network"

  compartment_ocid = var.compartment_ocid
  environment      = local.environment
  region           = var.region
}

module "vault" {
  source = "../../modules/vault"

  compartment_ocid = var.compartment_ocid
  environment      = local.environment
  region           = var.region
  fusion_pods      = keys(var.fusion_pods)
}

module "object_storage" {
  source = "../../modules/object_storage"

  compartment_ocid = var.compartment_ocid
  environment      = local.environment
  region           = var.region
  kms_key_id       = module.vault.key_id
}

module "atp" {
  source = "../../modules/atp"

  compartment_ocid         = var.compartment_ocid
  environment              = local.environment
  region                   = var.region
  subnet_id                = module.network.subnet_ids["db"]
  nsg_ids                  = [module.network.nsg_ids["db"]]
  vault_id                 = module.vault.vault_id
  key_id                   = module.vault.key_id
  admin_password_secret_id = module.vault.secret_ids["atp-admin-password"]
  compute_count            = var.atp_compute_count
  data_storage_size_in_gb  = var.atp_storage_gb
}

module "genai" {
  source = "../../modules/genai"

  compartment_ocid = var.compartment_ocid
  environment      = local.environment
  region           = var.region
  subnet_id        = module.network.subnet_ids["genai"]
  nsg_ids          = [module.network.nsg_ids["genai"]]
  genai_units      = var.genai_units
  genai_unit_shape = var.genai_unit_shape
}

module "iam" {
  source = "../../modules/iam"

  compartment_ocid  = var.compartment_ocid
  environment       = local.environment
  region            = var.region
  tenancy_ocid      = var.tenancy_ocid
  vault_id          = module.vault.vault_id
  key_id            = module.vault.key_id
  bucket_name       = "cashapp-${local.environment}-artifacts"
  genai_endpoint_id = module.genai.endpoint_id
}

module "observability" {
  source = "../../modules/observability"

  compartment_ocid = var.compartment_ocid
  environment      = local.environment
  region           = var.region
  alarm_emails     = var.alarm_emails
}

module "compute" {
  source = "../../modules/compute"

  compartment_ocid = var.compartment_ocid
  environment      = local.environment
  region           = var.region
  app_subnet_id    = module.network.subnet_ids["app"]
  lb_subnet_id     = module.network.subnet_ids["lb"]
  app_nsg_ids      = [module.network.nsg_ids["app"]]
  lb_nsg_ids       = [module.network.nsg_ids["lb"]]
  image_tag        = var.image_tag
  api_env          = local.api_env
  web_env          = local.web_env
  worker_groups    = var.worker_groups
  sizes            = var.sizes
  certificate_ocid = var.certificate_ocid
  api_hostname     = var.api_hostname
}
