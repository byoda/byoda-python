#!/bin/bash

# set -x

args=$(getopt -l "CAfile:" -l "cert:" -l "help" -o "-c:h" -- "$@")

eval set -- "$args"

while [ $# -ge 1 ]; do
    case "$1" in
        --)
            # No more options left.
            shift
            break
            ;;
        -h|--help)
            echo "$0 --CAfile <root-CA-file> --cert/-c <certificate-chain-file> : check certificate chain against a root certificate"
            echo ""
            exit 0
            ;;
        --CAfile)
            ROOT_PEM="$2"
            shift
            ;;
        --cert|-c)
            CHAIN_PEM="$2"
            shift
            ;;
    esac

    shift
done

if [[ -z "${ROOT_PEM}" || -z "${CHAIN_PEM}" ]]; then
    echo "Usage: $0 --CAfile <root-CA-file> --cert/-c <certificate-chain-file>" >&2
    exit 1
fi

if [[ ! -f "${ROOT_PEM}" ]]; then
    echo "$0: ${ROOT_PEM} is not a file" >&2
    exit 1
fi

if [[ ! -f "${CHAIN_PEM}" ]]; then
    echo "$0: ${CHAIN_PEM} is not a file" >&2
    exit 1
fi

if ! openssl x509 -in "${CHAIN_PEM}" -noout 2>/dev/null ; then
    echo "${CHAIN_PEM} is not a certificate" >&2
    exit 1
fi

if ! openssl x509 -in "${ROOT_PEM}" -noout 2>/dev/null ; then
    echo "${ROOT_PEM} is not a certificate" >&2
    exit 1
fi

awk -F'\n' '
        BEGIN {
            showcert = "openssl x509 -noout -subject -issuer"
        }

        /-----BEGIN CERTIFICATE-----/ {
            printf "%2d: ", ind
        }

        {
            printf $0"\n" | showcert
        }

        /-----END CERTIFICATE-----/ {
            close(showcert)
            ind ++
        }
    ' "${CHAIN_PEM}"

echo

openssl verify -CAfile ${ROOT_PEM} -untrusted "${CHAIN_PEM}" "${CHAIN_PEM}"
