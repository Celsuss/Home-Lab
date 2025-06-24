#!/bin/bash
set -e

helm template ../charts/root-app/ | kubectl apply -f - -n argo-cd
