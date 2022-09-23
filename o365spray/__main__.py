#!/usr/bin/env python3

import os
import sys
import time
import logging
import argparse
from random import randint
from pathlib import Path
from o365spray import __version__
from o365spray.core.handlers.validator import validate
from o365spray.core.handlers.enumerator import enumerate
from o365spray.core.handlers.sprayer import spray
from o365spray.core.utils import Helper
from o365spray.core.utils import init_logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "o365spray | Microsoft O365 User Enumerator and Password Sprayer"
            f" -- v{__version__}"
        )
    )

    parser.add_argument(
        "-d",
        "--domain",
        type=str,
        help=(
            "Target domain for validation, user enumeration, "
            "and/or password spraying."
        ),
    )

    # Type of action(s) to run
    parser.add_argument(
        "--validate", action="store_true", help="Run domain validation only."
    )
    parser.add_argument(  # Can be used with --spray
        "--enum", action="store_true", help="Run username enumeration."
    )
    parser.add_argument(  # Can be used with --enum
        "--spray", action="store_true", help="Run password spraying."
    )

    # Username(s)/Password(s) for enum/spray
    parser.add_argument(
        "-u", "--username", type=str, help="Username(s) delimited using commas."
    )
    parser.add_argument(
        "-p", "--password", type=str, help="Password(s) delimited using commas."
    )
    parser.add_argument(
        "-U", "--userfile", type=str, help="File containing list of usernames."
    )
    parser.add_argument(
        "-P", "--passfile", type=str, help="File containing list of passwords."
    )
    parser.add_argument(
        "--paired",
        type=str,
        help="File containing list of credentials in username:password format.",
    )

    # Password spraying lockout policy
    parser.add_argument(
        "-c",
        "--count",
        type=int,
        default=1,
        help=(
            "Number of password attempts to run per user before resetting the "
            "lockout account timer. Default: 1"
        ),
    )
    parser.add_argument(
        "-l",
        "--lockout",
        type=float,
        default=15.0,
        help="Lockout policy's reset time (in minutes). Default: 15 minutes",
    )

    # Validate/Spray/Enum action specifications
    parser.add_argument(
        "--validate-module",
        type=str.lower,
        default="getuserrealm",
        help="Specify which valiadtion module to run. Default: getuserrealm",
    )
    parser.add_argument(
        "--enum-module",
        type=str.lower,
        default="oauth2",
        help="Specify which enumeration module to run. Default: office",
    )
    parser.add_argument(
        "--spray-module",
        type=str.lower,
        default="oauth2",
        help="Specify which password spraying module to run. Default: oauth2",
    )
    parser.add_argument(
        "--adfs-url",
        type=str,
        help="AuthURL of the target domain's ADFS login page for password spraying.",
    )

    # General scan specifications
    parser.add_argument(
        "--sleep",
        type=int,
        default=0,
        choices=range(-1, 121),
        metavar="[-1, 0-120]",
        help=(
            "Throttle HTTP requests every `N` seconds. This can be randomized by "
            "passing the value `-1` (between 1 sec and 2 mins). Default: 0"
        ),
    )
    parser.add_argument(
        "--jitter",
        type=int,
        default=0,
        choices=range(0, 101),
        metavar="[0-100]",
        help="Jitter extends --sleep period by percentage given (0-100). Default: 0",
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=10,
        help=(
            "Number of concurrent connections (attempts) during enumeration and "
            "spraying. Default: 10"
        ),
    )
    parser.add_argument(
        "--safe",
        type=int,
        default=10,
        help=(
            "Terminate password spraying run if `N` locked accounts are observed. "
            "Default: 10"
        ),
    )

    # HTTP configurations
    parser.add_argument(
        "--timeout",
        type=int,
        default=25,
        help="HTTP request timeout in seconds. Default: 25",
    )
    parser.add_argument(
        "--proxy",
        type=str,
        help="HTTP/S proxy to pass traffic through (e.g. http://127.0.0.1:8080).",
    )
    parser.add_argument(
        "--proxy-url",
        type=str,
        help="FireProx API URL.",
    )

    # Misc configurations
    parser.add_argument(
        "--output",
        type=str,
        help=(
            "Output directory for results and test case files. "
            "Default: current directory"
        ),
    )
    parser.add_argument(
        "-v", "--version", action="store_true", help="Print the tool version."
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug output.")
    args = parser.parse_args()

    # If no flags provided, print the tool help and exit
    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(0)

    # Print the tool version and exit
    if args.version:
        print(f"o365spray -- {__version__}")
        sys.exit(0)

    # If not getting the tool version and flags have been provided, ensure
    # all required flags and valid flag combinations are present

    # Ensure a domain has been provided
    if not args.domain:
        parser.error("-d/--domain is required.")

    # If running user enumeration, make sure we have a username or username file
    if args.enum and (not args.username and not args.userfile):
        parser.error(
            "-u/--username or -U/--userfile is required when performing user "
            "enumeration via --enum."
        )

    # If running password spraying, make sure we have both username(s) and
    # password(s)
    if args.spray and (
        (
            (not args.username and not args.userfile)  # No username(s)
            or (not args.password and not args.passfile)  # No password(s)
        )
        and not args.paired  # Covers both username(s) and password(s)
    ):
        parser.error(
            "When running password spraying via --spray, the following flags are required: "
            "(-u/--username or -U/--userfile) and (-p/--password or -P/--passfile) -> "
            "otherwise, --paired is required."
        )

    # Handle sleep randomization
    if args.sleep == -1:
        args.sleep = randint(1, 120)

    return args


def main():
    """Main entry point for o365spray"""

    # Parse command line arguments
    args = parse_args()

    # Initialize logging level and format
    init_logger(args.debug)

    start = time.time()

    # Print banner with config settings
    Helper.banner(args, __version__)

    # If an output directory provided, get or create it
    if args.output:
        output_directory = args.output.strip("/")
        Path(output_directory).mkdir(parents=True, exist_ok=True)

    # If no output provided, default to the current working directory
    else:
        output_directory = os.getcwd()

    if args.adfs_url:
        # Skip domain validation and enforce ADFS enumeration/spraying
        # when the user provides an ADFS AuthURL
        if args.enum and args.enum_module != "oauth2":
            logging.info("Switching to oAuth2 module for user enumeration")
            args.enum_module = "oauth2"
        if args.spray and args.spray_module != "adfs":
            logging.info("Switching to ADFS module for password spraying")
            args.spray_module = "adfs"

    else:
        # Perform domain validation
        args = validate(args)

    # Perform user enumeration
    if args.enum:
        enum = enumerate(args, output_directory)
    else:
        enum = None

    if args.spray:
        spray(args, output_directory, enum)

    elapsed = time.time() - start
    logging.debug(f"o365spray executed in {elapsed:.2f} seconds.")


if __name__ == "__main__":
    main()
