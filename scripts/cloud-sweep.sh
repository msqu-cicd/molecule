#!/usr/bin/env bash
# Deletes leftover molecule test resources of one cloud, whatever the run that created them did.
#
#   cloud-sweep.sh hetzner|vultr|ec2
#
# Deleted: the resources of one repo (SWEEP_PROJECT, e.g. k3s; empty = none) and every molecule
# resource older than SWEEP_MAX_AGE_HOURS (default 3). Every failed query or deletion fails the
# script, after all other deletions were tried. SWEEP_DRY_RUN=true only prints what would go.
#
#   hetzner: HCLOUD_TOKEN. Servers labelled managed-by=molecule or named molecule-<project>[-nodeN],
#            then the unattached volumes and unused networks with that label, then the DynDNS
#            records *.<subdomain> of MOLECULE_DNS_ZONE whose subdomain has no molecule server left
#            (needs HETZNER_DNS_TOKEN, the Cloud API token of the project that holds the zone)
#   vultr:   VULTR_API_KEY. Instances labelled molecule-<repo>
#   ec2:     AWS credentials and AWS_DEFAULT_REGION. Instances tagged managed-by=molecule
set -euo pipefail

provider=${1:?usage: cloud-sweep.sh hetzner|vultr|ec2}
project=${SWEEP_PROJECT:-}
max_age=${SWEEP_MAX_AGE_HOURS:-3}
dry_run=${SWEEP_DRY_RUN:-false}
failed=0

# delete <description> <command...>
delete() {
  local what=$1
  shift
  if [ "$dry_run" = true ]; then
    echo "[dry run] would delete $what"
  else
    echo "Deleting $what"
    "$@" || {
      echo "Failed to delete $what" >&2
      failed=1
    }
  fi
}

# stdin: hcloud lines whose last field is an age (Xs, Xm, Xh up to 23h, then Xd, or "just now");
# prints the lines older than max_age hours
older() {
  awk -v max="$max_age" '{ a = $NF; u = substr(a, length(a)); n = substr(a, 1, length(a) - 1) + 0; if (u == "d" || (u == "h" && n >= max)) print }'
}

# Failed list calls abort the script (set -e, pipefail): "the API cannot be queried" must not read
# as "nothing found".
sweep_hetzner() {
  local all labelled victims gone volumes networks zone
  all=$(hcloud server list -o noheader -o columns=id,name)
  labelled=$(hcloud server list -l managed-by=molecule -o noheader -o columns=id,name,age)

  echo "Hetzner servers: molecule-${project:-<none>}[-nodeN] and labelled managed-by=molecule older than ${max_age}h"
  victims=$(
    {
      if [ -n "$project" ]; then
        awk -v re="^molecule-${project}(-node[0-9]+)?\$" '$2 ~ re { print $1, $2 }' <<< "$all"
      fi
      older <<< "$labelled" | awk '{ print $1, $2 }'
    } | sort -u
  )
  gone=$victims
  while read -r id name; do
    [ -n "$id" ] || continue
    delete "server $name ($id)" hcloud server delete "$id"
  done <<< "$victims"

  # destroy.yml removes volumes and networks only while the platform's server exists. What the servers
  # above left behind: unattached volumes and networks without servers, of this repo or old.
  volumes=$(hcloud volume list -l managed-by=molecule -o noheader -o columns=id,name,server,age)
  victims=$(
    {
      if [ -n "$project" ]; then
        hcloud volume list -l "managed-by=molecule,project=$project" -o noheader -o columns=id,name,server,age
      fi
      older <<< "$volumes"
    } | awk '$3 == "-" { print $1, $2 }' | sort -u
  )
  while read -r id name; do
    [ -n "$id" ] || continue
    delete "volume $name ($id)" hcloud volume delete "$id"
  done <<< "$victims"

  # the servers column reads "N server(s)", so the age is the last field and N the third
  networks=$(hcloud network list -l managed-by=molecule -o noheader -o columns=id,name,servers,age)
  victims=$(
    {
      if [ -n "$project" ]; then
        hcloud network list -l "managed-by=molecule,project=$project" -o noheader -o columns=id,name,servers,age
      fi
      older <<< "$networks"
    } | awk '$3 == 0 { print $1, $2 }' | sort -u
  )
  while read -r id name; do
    [ -n "$id" ] || continue
    delete "network $name ($id)" hcloud network delete "$id"
  done <<< "$victims"

  zone=${MOLECULE_DNS_ZONE:-}
  if [ -z "$zone" ] || [ -z "${HETZNER_DNS_TOKEN:-}" ]; then
    echo "DynDNS records: skipped (MOLECULE_DNS_ZONE or HETZNER_DNS_TOKEN not set)"
  else
    sweep_hetzner_dns "$zone" "$all" "$gone"
  fi
}

# DynDNS records of dyndns.yml: *.<subdomain>, A and AAAA, subdomain = repo name (the servers are
# molecule-<subdomain>[-nodeN]). A record without a server of that name is a leftover: the role-side
# cleanup is opt-in and does not run after a cancel. $1 zone, $2 the servers (id name) from before the
# deletions, $3 the ones deleted (they count as gone, also in a dry run).
sweep_hetzner_dns() {
  local zone=$1 all=$2 gone=$3 live records name type sub
  live=$(awk 'NR == FNR { g[$1] = 1; next } !($1 in g) && $2 ~ /^molecule-/ { n = $2; sub(/^molecule-/, "", n); sub(/-node[0-9]+$/, "", n); print n }' \
    <(printf '%s\n' "$gone") <(printf '%s\n' "$all") | sort -u)
  # the zone may live in another project than the servers
  records=$(HCLOUD_TOKEN="$HETZNER_DNS_TOKEN" hcloud zone rrset list "$zone" --type A --type AAAA -o noheader -o columns=name,type)
  echo "DynDNS records in $zone without a molecule server"
  while read -r name type; do
    case $name in
      '*.'*) ;;
      *) continue ;;
    esac
    sub=${name#\*.}
    case $sub in
      '' | *[!a-z0-9-]*) continue ;;
    esac
    if grep -qxF -- "$sub" <<< "$live"; then
      continue
    fi
    delete "DNS record $name $type in $zone" env HCLOUD_TOKEN="$HETZNER_DNS_TOKEN" hcloud zone rrset delete "$zone" "$name" "$type"
  done <<< "$records"
}

sweep_vultr() {
  local all victims
  all=$(vultr-cli instance list --per-page 500 --output json)
  echo "Vultr instances: molecule-${project:-<none>} and labelled molecule-* older than ${max_age}h"
  # date_created reads 2020-10-10T01:56:20+00:00
  victims=$(
    jq -r --arg mine "molecule-$project" --argjson max "$max_age" '
      .instances[]?
      | select((.label // "") | startswith("molecule-"))
      | select(.label == $mine or ((.date_created | sub("(\\.[0-9]+)?(\\+00:00|Z)$"; "Z") | fromdateiso8601) < (now - $max * 3600)))
      | "\(.id) \(.label)"' <<< "$all"
  )
  while read -r id label; do
    [ -n "$id" ] || continue
    delete "instance $label ($id)" vultr-cli instance delete "$id"
  done <<< "$victims"
}

sweep_ec2() {
  SWEEP_PROJECT=$project SWEEP_MAX_AGE_HOURS=$max_age SWEEP_DRY_RUN=$dry_run python3 - << 'PY'
import datetime, os, sys
import boto3

project = os.environ["SWEEP_PROJECT"]
cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=float(os.environ["SWEEP_MAX_AGE_HOURS"]))
dry_run = os.environ["SWEEP_DRY_RUN"] == "true"
ec2 = boto3.client("ec2")
# raises if the API cannot be queried instead of reporting "nothing found"
reservations = ec2.describe_instances(Filters=[
    {"Name": "tag:managed-by", "Values": ["molecule"]},
    {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
])["Reservations"]
doomed = []
for instance in (i for r in reservations for i in r["Instances"]):
    tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
    reason = "this repo" if project and tags.get("project") == project else "older than the limit" if instance["LaunchTime"] < cutoff else None
    if reason:
        print(f"{'[dry run] would terminate' if dry_run else 'Terminating'} {instance['InstanceId']} ({tags.get('Name')}, {reason})")
        doomed.append(instance["InstanceId"])
if doomed and not dry_run:
    ec2.terminate_instances(InstanceIds=doomed)
elif not doomed:
    print("No leftover molecule instances")
PY
}

case $provider in
  hetzner) sweep_hetzner ;;
  vultr) sweep_vultr ;;
  ec2) sweep_ec2 ;;
  *)
    echo "unknown provider '$provider' (hetzner, vultr or ec2)" >&2
    exit 2
    ;;
esac
exit "$failed"
