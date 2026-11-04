variable "name_prefix" { type = string }
variable "secret_arns_by_runtime" {
  description = "Existing Secrets Manager ARNs keyed by the runtime allowed to inject them."
  type        = map(set(string))
  validation {
    condition = length(keys(var.secret_arns_by_runtime)) == 4 && alltrue([
      for runtime in ["api", "worker", "assurance", "migrator"] : contains(keys(var.secret_arns_by_runtime), runtime)
    ])
    error_message = "secret_arns_by_runtime must contain exactly api, worker, assurance, and migrator entries."
  }
}
variable "tags" {
  type    = map(string)
  default = {}
}
