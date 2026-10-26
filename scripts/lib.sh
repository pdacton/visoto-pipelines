# Shared settings and helpers. Source it: `. "$(dirname "$0")/../../scripts/lib.sh"`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$ROOT/.tools"

SPARQL_ANYTHING_VERSION=1.2.0
JENA_VERSION=6.2.0
JQ_VERSION=1.8.1

SA_JAR="$TOOLS/sparql-anything-v$SPARQL_ANYTHING_VERSION.jar"
JENA_HOME="$TOOLS/apache-jena-$JENA_VERSION"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# Download pinned tools into .tools/ unless already there.
ensure_tools() {
  mkdir -p "$TOOLS/bin"
  # A JRE unpacked into .tools/ (local setup) wins over the PATH.
  local jre
  jre=$(ls -d "$TOOLS"/jdk-*/bin 2>/dev/null | head -1 || true)
  [ -n "$jre" ] && export PATH="$jre:$PATH"
  command -v java >/dev/null || die "java 21+ not found (install it or unpack a JRE into .tools/)"

  if [ ! -f "$SA_JAR" ]; then
    log "downloading SPARQL Anything $SPARQL_ANYTHING_VERSION"
    curl -fsSL -o "$SA_JAR.part" \
      "https://github.com/SPARQL-Anything/sparql.anything/releases/download/v$SPARQL_ANYTHING_VERSION/sparql-anything-v$SPARQL_ANYTHING_VERSION.jar"
    mv "$SA_JAR.part" "$SA_JAR"
  fi
  if [ ! -d "$JENA_HOME" ]; then
    log "downloading Apache Jena $JENA_VERSION"
    curl -fsSL "https://archive.apache.org/dist/jena/binaries/apache-jena-$JENA_VERSION.tar.gz" | tar xz -C "$TOOLS"
  fi
  if ! command -v jq >/dev/null; then
    if [ ! -x "$TOOLS/bin/jq" ]; then
      log "downloading jq $JQ_VERSION"
      curl -fsSL -o "$TOOLS/bin/jq" "https://github.com/jqlang/jq/releases/download/jq-$JQ_VERSION/jq-linux-amd64"
      chmod +x "$TOOLS/bin/jq"
    fi
    export PATH="$TOOLS/bin:$PATH"
  fi
}

# Run a SPARQL Anything query file: sa <query> <output> [format]
sa() {
  java -Xmx2g -jar "$SA_JAR" -q "$1" -o "$2" -f "${3:-NT}" 2> >(grep -v ' INFO ' >&2)
}

riot()  { "$JENA_HOME/bin/riot" -q "$@"; }
shacl() { "$JENA_HOME/bin/shacl" "$@"; }
arq()   { "$JENA_HOME/bin/arq" "$@"; }

# curl with retries for flaky public APIs
fetch() { curl -fsSL --retry 4 --retry-delay 5 --retry-all-errors "$@"; }

# Load pipelines/<name>/pipeline.env and set PIPELINE_DIR, RAW, OUT.
load_pipeline() {
  PIPELINE_DIR="$ROOT/pipelines/$1"
  [ -f "$PIPELINE_DIR/pipeline.env" ] || die "unknown pipeline: $1"
  # shellcheck disable=SC1091
  . "$PIPELINE_DIR/pipeline.env"
  RAW="$PIPELINE_DIR/raw"
  OUT="$PIPELINE_DIR/out"
}
