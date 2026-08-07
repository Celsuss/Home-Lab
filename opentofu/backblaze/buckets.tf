resource "b2_bucket" "volsync" {
  for_each = var.buckets

  bucket_name = each.key
  bucket_type = "allPrivate"

  lifecycle_rules {
    file_name_prefix              = ""
    days_from_uploading_to_hiding = 0
    days_from_hiding_to_deleting  = each.value.lifecycle_days
  }

  default_server_side_encryption {
    algorithm = "AES256"
    mode      = "SSE-B2"
  }
}

resource "b2_application_key" "volsync" {
  for_each = var.buckets

  key_name     = "${each.key}-volsync"
  capabilities = ["listBuckets", "listFiles", "readFiles", "writeFiles", "deleteFiles"]
  bucket_ids   = [b2_bucket.volsync[each.key].bucket_id]
}
