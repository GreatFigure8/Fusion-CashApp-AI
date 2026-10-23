data "oci_objectstorage_namespace" "this" {
  compartment_id = var.compartment_ocid
}

data "oci_identity_availability_domains" "this" {
  compartment_id = var.compartment_ocid
}

locals {
  name         = "cashapp-${var.environment}"
  ocir_base    = "iad.ocir.io/${data.oci_objectstorage_namespace.this.namespace}/cashapp"
  api_image    = "${local.ocir_base}/api:${var.image_tag}"
  web_image    = "${local.ocir_base}/web:${var.image_tag}"
  ad_name      = data.oci_identity_availability_domains.this.availability_domains[0].name
  shape        = "CI.Standard.E4.Flex"
  worker_names = { for g, roles in var.worker_groups : "worker-${g}" => roles }
}

# Images are immutable per tag; the release pushes a new tag and re-applies with -var image_tag.
resource "oci_artifacts_container_repository" "api" {
  compartment_id = var.compartment_ocid
  display_name   = "cashapp/api"
  is_public      = false
  is_immutable   = true
  freeform_tags  = local.tags
}

resource "oci_artifacts_container_repository" "web" {
  compartment_id = var.compartment_ocid
  display_name   = "cashapp/web"
  is_public      = false
  is_immutable   = true
  freeform_tags  = local.tags
}

resource "oci_container_instances_container_instance" "api" {
  compartment_id           = var.compartment_ocid
  availability_domain      = local.ad_name
  display_name             = "${local.name}-api"
  shape                    = local.shape
  container_restart_policy = "ALWAYS"
  freeform_tags            = local.tags

  shape_config {
    ocpus         = lookup(var.sizes, "api", var.sizes["default"]).ocpus
    memory_in_gbs = lookup(var.sizes, "api", var.sizes["default"]).memory_in_gbs
  }

  vnics {
    subnet_id             = var.app_subnet_id
    nsg_ids               = var.app_nsg_ids
    is_public_ip_assigned = false
  }

  containers {
    display_name          = "api"
    image_url             = local.api_image
    command               = ["uvicorn"]
    arguments             = ["cashapp.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
    environment_variables = var.api_env

    health_checks {
      health_check_type   = "HTTP"
      port                = 8000
      path                = "/health"
      interval_in_seconds = 15
      failure_threshold   = 3
      failure_action      = "KILL"
    }
  }

  depends_on = [oci_artifacts_container_repository.api]
}

resource "oci_container_instances_container_instance" "web" {
  compartment_id           = var.compartment_ocid
  availability_domain      = local.ad_name
  display_name             = "${local.name}-web"
  shape                    = local.shape
  container_restart_policy = "ALWAYS"
  freeform_tags            = local.tags

  shape_config {
    ocpus         = lookup(var.sizes, "web", var.sizes["default"]).ocpus
    memory_in_gbs = lookup(var.sizes, "web", var.sizes["default"]).memory_in_gbs
  }

  vnics {
    subnet_id             = var.app_subnet_id
    nsg_ids               = var.app_nsg_ids
    is_public_ip_assigned = false
  }

  containers {
    display_name          = "web"
    image_url             = local.web_image
    environment_variables = var.web_env

    health_checks {
      health_check_type   = "HTTP"
      port                = 3000
      path                = "/"
      interval_in_seconds = 15
      failure_threshold   = 3
      failure_action      = "KILL"
    }
  }

  depends_on = [oci_artifacts_container_repository.web]
}

# One instance per worker role group. The same image as the api; only the command differs.
resource "oci_container_instances_container_instance" "worker" {
  for_each = local.worker_names

  compartment_id           = var.compartment_ocid
  availability_domain      = local.ad_name
  display_name             = "${local.name}-${each.key}"
  shape                    = local.shape
  container_restart_policy = "ALWAYS"
  freeform_tags            = local.tags

  shape_config {
    ocpus         = lookup(var.sizes, each.key, var.sizes["default"]).ocpus
    memory_in_gbs = lookup(var.sizes, each.key, var.sizes["default"]).memory_in_gbs
  }

  vnics {
    subnet_id             = var.app_subnet_id
    nsg_ids               = var.app_nsg_ids
    is_public_ip_assigned = false
  }

  containers {
    display_name          = each.key
    image_url             = local.api_image
    command               = ["python", "-m", "cashapp.workers", "run"]
    arguments             = ["--roles", join(",", each.value)]
    environment_variables = var.api_env

    health_checks {
      health_check_type   = "HTTP"
      port                = 8081
      path                = "/readyz"
      interval_in_seconds = 15
      failure_threshold   = 3
      failure_action      = "KILL"
    }
  }

  depends_on = [oci_artifacts_container_repository.api]
}

data "oci_core_vnic" "api" {
  vnic_id = oci_container_instances_container_instance.api.vnics[0].vnic_id
}

data "oci_core_vnic" "web" {
  vnic_id = oci_container_instances_container_instance.web.vnics[0].vnic_id
}

resource "oci_load_balancer_load_balancer" "this" {
  compartment_id             = var.compartment_ocid
  display_name               = "${local.name}-lb"
  shape                      = "flexible"
  subnet_ids                 = [var.lb_subnet_id]
  network_security_group_ids = var.lb_nsg_ids
  is_private                 = false
  freeform_tags              = local.tags

  shape_details {
    minimum_bandwidth_in_mbps = var.lb_min_bandwidth_mbps
    maximum_bandwidth_in_mbps = var.lb_max_bandwidth_mbps
  }
}

resource "oci_load_balancer_backend_set" "api" {
  load_balancer_id = oci_load_balancer_load_balancer.this.id
  name             = "api"
  policy           = "ROUND_ROBIN"

  health_checker {
    protocol          = "HTTP"
    port              = 8000
    url_path          = "/health"
    return_code       = 200
    interval_ms       = 10000
    timeout_in_millis = 3000
    retries           = 3
  }
}

resource "oci_load_balancer_backend_set" "web" {
  load_balancer_id = oci_load_balancer_load_balancer.this.id
  name             = "web"
  policy           = "ROUND_ROBIN"

  health_checker {
    protocol          = "HTTP"
    port              = 3000
    url_path          = "/"
    return_code       = 200
    interval_ms       = 10000
    timeout_in_millis = 3000
    retries           = 3
  }
}

resource "oci_load_balancer_backend" "api" {
  load_balancer_id = oci_load_balancer_load_balancer.this.id
  backendset_name  = oci_load_balancer_backend_set.api.name
  ip_address       = data.oci_core_vnic.api.private_ip_address
  port             = 8000
}

resource "oci_load_balancer_backend" "web" {
  load_balancer_id = oci_load_balancer_load_balancer.this.id
  backendset_name  = oci_load_balancer_backend_set.web.name
  ip_address       = data.oci_core_vnic.web.private_ip_address
  port             = 3000
}

# Requests for the api hostname go to the api backend set; everything else goes to web.
# VERIFY the Host header condition syntax on the first plan/apply.
resource "oci_load_balancer_load_balancer_routing_policy" "hosts" {
  load_balancer_id           = oci_load_balancer_load_balancer.this.id
  name                       = "hosts"
  condition_language_version = "V1"

  rules {
    name      = "api_host"
    condition = "any(http.request.headers[(i 'Host')] eq (i '${var.api_hostname}'))"

    actions {
      name             = "FORWARD_TO_BACKENDSET"
      backend_set_name = oci_load_balancer_backend_set.api.name
    }
  }
}

resource "oci_load_balancer_listener" "https" {
  load_balancer_id         = oci_load_balancer_load_balancer.this.id
  name                     = "https"
  default_backend_set_name = oci_load_balancer_backend_set.web.name
  port                     = 443
  protocol                 = "HTTP"
  routing_policy_name      = oci_load_balancer_load_balancer_routing_policy.hosts.name

  ssl_configuration {
    certificate_ids         = [var.certificate_ocid]
    protocols               = ["TLSv1.2", "TLSv1.3"]
    server_order_preference = "ENABLED"
  }
}
