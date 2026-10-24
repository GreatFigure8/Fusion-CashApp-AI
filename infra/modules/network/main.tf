data "oci_core_services" "all" {
  filter {
    name   = "name"
    values = ["All .* Services In Oracle Services Network"]
    regex  = true
  }
}

locals {
  name        = "cashapp-${var.environment}"
  all_service = data.oci_core_services.all.services[0]
}

resource "oci_core_vcn" "this" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = [var.vcn_cidr]
  display_name   = local.name
  dns_label      = "cashapp${var.environment}"
  freeform_tags  = local.tags
}

# Only the load balancer subnet is routed to the internet.
resource "oci_core_internet_gateway" "this" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${local.name}-igw"
  enabled        = true
  freeform_tags  = local.tags
}

resource "oci_core_nat_gateway" "this" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${local.name}-nat"
  block_traffic  = false
  freeform_tags  = local.tags
}

resource "oci_core_service_gateway" "this" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${local.name}-sgw"
  freeform_tags  = local.tags

  services {
    service_id = local.all_service.id
  }
}

resource "oci_core_route_table" "public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${local.name}-public"
  freeform_tags  = local.tags

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.this.id
  }
}

resource "oci_core_route_table" "private" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${local.name}-private"
  freeform_tags  = local.tags

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_nat_gateway.this.id
  }

  route_rules {
    destination       = local.all_service.cidr_block
    destination_type  = "SERVICE_CIDR_BLOCK"
    network_entity_id = oci_core_service_gateway.this.id
  }
}

# Traffic is controlled by the NSGs below. This security list carries no rules,
# so the VCN's permissive default list is never attached to a subnet.
resource "oci_core_security_list" "empty" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${local.name}-empty"
  freeform_tags  = local.tags
}

resource "oci_core_subnet" "lb" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.this.id
  cidr_block                 = var.subnet_cidrs["lb"]
  display_name               = "${local.name}-lb"
  dns_label                  = "lb"
  prohibit_public_ip_on_vnic = false
  route_table_id             = oci_core_route_table.public.id
  security_list_ids          = [oci_core_security_list.empty.id]
  freeform_tags              = local.tags
}

resource "oci_core_subnet" "app" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.this.id
  cidr_block                 = var.subnet_cidrs["app"]
  display_name               = "${local.name}-app"
  dns_label                  = "app"
  prohibit_public_ip_on_vnic = true
  route_table_id             = oci_core_route_table.private.id
  security_list_ids          = [oci_core_security_list.empty.id]
  freeform_tags              = local.tags
}

resource "oci_core_subnet" "db" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.this.id
  cidr_block                 = var.subnet_cidrs["db"]
  display_name               = "${local.name}-db"
  dns_label                  = "db"
  prohibit_public_ip_on_vnic = true
  route_table_id             = oci_core_route_table.private.id
  security_list_ids          = [oci_core_security_list.empty.id]
  freeform_tags              = local.tags
}

resource "oci_core_subnet" "genai" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.this.id
  cidr_block                 = var.subnet_cidrs["genai"]
  display_name               = "${local.name}-genai"
  dns_label                  = "genai"
  prohibit_public_ip_on_vnic = true
  route_table_id             = oci_core_route_table.private.id
  security_list_ids          = [oci_core_security_list.empty.id]
  freeform_tags              = local.tags
}

resource "oci_core_network_security_group" "lb" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${local.name}-lb"
  freeform_tags  = local.tags
}

resource "oci_core_network_security_group" "app" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${local.name}-app"
  freeform_tags  = local.tags
}

resource "oci_core_network_security_group" "db" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${local.name}-db"
  freeform_tags  = local.tags
}

resource "oci_core_network_security_group" "genai" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${local.name}-genai"
  freeform_tags  = local.tags
}

locals {
  nsg = {
    lb        = oci_core_network_security_group.lb.id
    app       = oci_core_network_security_group.app.id
    db        = oci_core_network_security_group.db.id
    genai     = oci_core_network_security_group.genai.id
  }

  # One entry per TCP rule. peer is a CIDR block or an NSG key from local.nsg.
  rules = {
    lb_in_https       = { nsg = "lb", direction = "INGRESS", peer = "0.0.0.0/0", min = 443, max = 443, description = "Internet to load balancer HTTPS" }
    lb_out_api        = { nsg = "lb", direction = "EGRESS", peer = "app", min = 8000, max = 8000, description = "Load balancer to api" }
    lb_out_web        = { nsg = "lb", direction = "EGRESS", peer = "app", min = 3000, max = 3000, description = "Load balancer to web" }
    lb_out_health     = { nsg = "lb", direction = "EGRESS", peer = "app", min = 8081, max = 8081, description = "Load balancer to worker health" }
    app_in_api        = { nsg = "app", direction = "INGRESS", peer = "lb", min = 8000, max = 8000, description = "api from load balancer" }
    app_in_web        = { nsg = "app", direction = "INGRESS", peer = "lb", min = 3000, max = 3000, description = "web from load balancer" }
    app_in_health     = { nsg = "app", direction = "INGRESS", peer = "lb", min = 8081, max = 8081, description = "worker health from load balancer" }
    app_out_db        = { nsg = "app", direction = "EGRESS", peer = "db", min = 1521, max = 1522, description = "app to database" }
    app_out_genai     = { nsg = "app", direction = "EGRESS", peer = "genai", min = 443, max = 443, description = "app to generative AI private endpoint" }
    app_out_https     = { nsg = "app", direction = "EGRESS", peer = "0.0.0.0/0", min = 443, max = 443, description = "app to Anthropic API, Fusion and OCI services via NAT" }
    db_in_app         = { nsg = "db", direction = "INGRESS", peer = "app", min = 1521, max = 1522, description = "database from app" }
    genai_in_app      = { nsg = "genai", direction = "INGRESS", peer = "app", min = 443, max = 443, description = "generative AI endpoint from app" }
  }
}

resource "oci_core_network_security_group_security_rule" "this" {
  for_each = local.rules

  network_security_group_id = local.nsg[each.value.nsg]
  direction                 = each.value.direction
  protocol                  = "6"
  description               = each.value.description
  stateless                 = false

  source           = each.value.direction == "INGRESS" ? lookup(local.nsg, each.value.peer, each.value.peer) : null
  source_type      = each.value.direction == "INGRESS" ? (contains(keys(local.nsg), each.value.peer) ? "NETWORK_SECURITY_GROUP" : "CIDR_BLOCK") : null
  destination      = each.value.direction == "EGRESS" ? lookup(local.nsg, each.value.peer, each.value.peer) : null
  destination_type = each.value.direction == "EGRESS" ? (contains(keys(local.nsg), each.value.peer) ? "NETWORK_SECURITY_GROUP" : "CIDR_BLOCK") : null

  tcp_options {
    destination_port_range {
      min = each.value.min
      max = each.value.max
    }
  }
}
