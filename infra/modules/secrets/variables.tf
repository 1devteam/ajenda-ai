variable "name_prefix" {
  type = string
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "redis_auth_token" {
  type      = string
  sensitive = true
}

variable "oidc_signing_key_pem" {
  type      = string
  sensitive = true
}

variable "webhook_hmac_master_key" {
  type      = string
  sensitive = true
}

variable "tags" {
  type    = map(string)
  default = {}
}