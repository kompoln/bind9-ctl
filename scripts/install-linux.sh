#!/usr/bin/env bash
set -euo pipefail

# install-linux.sh
# Installs bind9-ctl and its runtime dependencies on a Linux server.

INSTALL_PREFIX=${INSTALL_PREFIX:-/opt/bind9-ctl}
CLI_LINK=${CLI_LINK:-/usr/local/bin/bind9-ctl}
SKIP_SYSTEM_PACKAGES=${SKIP_SYSTEM_PACKAGES:-0}
PYTHON_BIN=${PYTHON_BIN:-python3}
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV_DIR="${INSTALL_PREFIX}/.venv"

info() {
  echo "[INFO] $*"
}

warn() {
  echo "[WARN] $*" >&2
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

require_root() {
  if [[ ${EUID} -ne 0 ]]; then
    die "This installer must run as root (or via sudo)."
  fi
}

detect_package_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
  elif command -v dnf >/dev/null 2>&1; then
    echo "dnf"
  elif command -v yum >/dev/null 2>&1; then
    echo "yum"
  elif command -v zypper >/dev/null 2>&1; then
    echo "zypper"
  elif command -v pacman >/dev/null 2>&1; then
    echo "pacman"
  else
    echo ""
  fi
}

install_system_packages() {
  local manager packages update_cmd install_cmd
  manager=$(detect_package_manager)
  if [[ -z "${manager}" ]]; then
    warn "Unsupported package manager; install python3, python3-venv, pip, and BIND utilities manually."
    return
  fi

  case "${manager}" in
    apt)
      packages=(python3 python3-venv python3-pip bind9-utils git)
      update_cmd=(apt-get update)
      install_cmd=(apt-get install -y "${packages[@]}")
      ;;
    dnf|yum)
      packages=(python3 python3-pip bind-utils bind git)
      update_cmd=("${manager}" -y check-update || true)
      install_cmd=("${manager}" install -y "${packages[@]}")
      ;;
    zypper)
      packages=(python311 python311-pip python311-venv bind-utils git)
      update_cmd=(zypper refresh)
      install_cmd=(zypper install -y "${packages[@]}")
      ;;
    pacman)
      packages=(python python-pip python-virtualenv bind git)
      update_cmd=(pacman -Sy)
      install_cmd=(pacman -S --noconfirm "${packages[@]}")
      ;;
    *)
      warn "Package manager ${manager} unsupported; skipping package installation."
      return
      ;;
  esac

  info "Installing system packages via ${manager}: ${packages[*]}"
  "${update_cmd[@]}"
  "${install_cmd[@]}"
}

copy_project_files() {
  info "Copying project files to ${INSTALL_PREFIX}"
  mkdir -p "${INSTALL_PREFIX}"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude ".git/" \
      --exclude ".venv/" \
      --exclude "__pycache__/" \
      --exclude "*.pyc" \
      --exclude "zones/*.zone" \
      "${REPO_ROOT}/" "${INSTALL_PREFIX}/"
  else
    warn "rsync not available; falling back to cp (existing files will not be deleted)."
    cp -a "${REPO_ROOT}/." "${INSTALL_PREFIX}/"
  fi
}

ensure_env_file() {
  local example_file="${INSTALL_PREFIX}/.env.example"
  local env_file="${INSTALL_PREFIX}/.env"
  if [[ ! -f "${env_file}" ]]; then
    if [[ -f "${example_file}" ]]; then
      info "Creating initial .env from .env.example"
      cp "${example_file}" "${env_file}"
    else
      warn "No .env.example found; create ${env_file} manually."
    fi
  else
    info "Preserving existing ${env_file}"
  fi
}

create_virtualenv() {
  if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    die "Python executable '${PYTHON_BIN}' not found."
  fi

  info "Creating virtual environment in ${VENV_DIR}"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install --upgrade pip
  (cd "${INSTALL_PREFIX}" && "${VENV_DIR}/bin/pip" install -e .)
}

create_wrapper_script() {
  local link_path="${CLI_LINK}"
  local wrapper

  mkdir -p "$(dirname "${link_path}")"

  wrapper=$(cat <<EOF
#!/usr/bin/env bash
set -euo pipefail
ROOT="${INSTALL_PREFIX}"
if [[ ! -f "\${ROOT}/.venv/bin/activate" ]]; then
  echo "bind9-ctl virtual environment not found under \${ROOT}" >&2
  exit 1
fi
source "\${ROOT}/.venv/bin/activate"
cd "\${ROOT}"
exec python -m bind9_ctl.cli "\$@"
EOF
)

  info "Creating CLI wrapper at ${link_path}"
  printf '%s\n' "${wrapper}" > "${link_path}"
  chmod +x "${link_path}"
}

main() {
  require_root

  if [[ "${SKIP_SYSTEM_PACKAGES}" != "1" ]]; then
    install_system_packages
  else
    info "Skipping system package installation per SKIP_SYSTEM_PACKAGES"
  fi

  copy_project_files
  ensure_env_file
  create_virtualenv
  create_wrapper_script

  cat <<EOM

bind9-ctl has been installed to ${INSTALL_PREFIX}
Wrapper script created at ${CLI_LINK}

Next steps:
  1. Edit ${INSTALL_PREFIX}/.env to match your environment (BIND server, TSIG, strategy).
  2. Run 'bind9-ctl pull --zone example.com.' to verify connectivity.
  3. Use 'bind9-ctl plan/apply' as needed. The tool runs inside its dedicated virtualenv automatically.

Tip: set APPLY_STRATEGY=dynamic in .env when remote rndc access is unavailable.
EOM
}

main "$@"

