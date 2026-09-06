#!/usr/bin/env python3

"""Validate HammerSim rank/bank/row device-map JSON files."""

import argparse
import json
from pathlib import Path


def coordinate(key, level, path):
    if key == "*":
        return
    if (
        not key.isascii()
        or not key.isdecimal()
        or str(int(key)) != key
    ):
        raise ValueError(
            f"{path}: {level} key {key!r} must be '*' or a canonical "
            "non-negative decimal integer"
        )


def validate(path, row_buffer_size=None):
    try:
        with path.open(encoding="utf-8") as stream:
            device_map = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: unable to read device map: {error}") from error

    if not isinstance(device_map, dict) or not device_map:
        raise ValueError(f"{path}: top-level rank map must be a non-empty object")

    for rank, banks in device_map.items():
        coordinate(rank, "rank", path)
        if not isinstance(banks, dict) or not banks:
            raise ValueError(f"{path}: rank {rank!r} must contain banks")
        for bank, rows in banks.items():
            coordinate(bank, "bank", path)
            if not isinstance(rows, dict) or not rows:
                raise ValueError(
                    f"{path}: rank {rank!r}, bank {bank!r} must contain rows"
                )
            for row, columns in rows.items():
                coordinate(row, "row", path)
                if not isinstance(columns, list) or not columns:
                    raise ValueError(
                        f"{path}: rank {rank!r}, bank {bank!r}, row "
                        f"{row!r} must contain a non-empty column list"
                    )
                if any(
                    isinstance(column, bool)
                    or not isinstance(column, int)
                    or column < 0
                    for column in columns
                ):
                    raise ValueError(
                        f"{path}: rank {rank!r}, bank {bank!r}, row "
                        f"{row!r} contains a non-integer or negative column"
                    )
                if len(columns) != len(set(columns)):
                    raise ValueError(
                        f"{path}: rank {rank!r}, bank {bank!r}, row "
                        f"{row!r} contains duplicate columns"
                    )
                if row_buffer_size is not None and any(
                    column >= row_buffer_size for column in columns
                ):
                    raise ValueError(
                        f"{path}: rank {rank!r}, bank {bank!r}, row "
                        f"{row!r} contains a column outside the "
                        f"{row_buffer_size}-byte row buffer"
                    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--row-buffer-size",
        type=int,
        help="Optionally reject byte columns outside this row-buffer size.",
    )
    parser.add_argument("maps", nargs="+", type=Path)
    args = parser.parse_args()
    if args.row_buffer_size is not None and args.row_buffer_size <= 0:
        parser.error("--row-buffer-size must be greater than zero")

    errors = []
    for path in args.maps:
        try:
            validate(path, args.row_buffer_size)
        except ValueError as error:
            errors.append(str(error))

    if errors:
        parser.exit(1, "\n".join(errors) + "\n")


if __name__ == "__main__":
    main()
