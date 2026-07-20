terraform {
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.31"
    }
  }
}

provider "kubernetes" {
  config_path    = "~/.kube/config"
  config_context = "kind-lab"
}

resource "kubernetes_namespace" "lab_namespace" {
  metadata {
    name = "terraform-lab"
  }
}