import argparse

from app.services.auth_store_service import (
    add_row_permission,
    auth_db_path,
    bind_user_group,
    ensure_auth_db,
    remove_row_permission,
    set_user_enabled,
    upsert_permission_group,
    upsert_user,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage local ChatSQL SQLite auth data.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create auth.sqlite3 and default admin/user accounts.")

    user = sub.add_parser("upsert-user", help="Create or update a user.")
    user.add_argument("--username", required=True)
    user.add_argument("--password", required=True)
    user.add_argument("--role", choices=["admin", "user"], required=True)
    user.add_argument("--disabled", action="store_true")

    disable = sub.add_parser("disable-user", help="Disable a user.")
    disable.add_argument("--username", required=True)

    enable = sub.add_parser("enable-user", help="Enable a user.")
    enable.add_argument("--username", required=True)

    group = sub.add_parser("upsert-group", help="Create or update a permission group.")
    group.add_argument("--name", required=True)
    group.add_argument("--description", default="")
    group.add_argument("--disabled", action="store_true")

    bind = sub.add_parser("bind-group", help="Bind a user to a permission group.")
    bind.add_argument("--username", required=True)
    bind.add_argument("--group", required=True)
    bind.add_argument("--disabled", action="store_true")

    add_perm = sub.add_parser("add-row-permission", help="Add or enable a row permission.")
    add_perm.add_argument("--group", required=True)
    add_perm.add_argument("--dataset-id", default="*")
    add_perm.add_argument("--table", required=True)
    add_perm.add_argument("--column", required=True)
    add_perm.add_argument("--operator", default="=")
    add_perm.add_argument("--value", required=True)
    add_perm.add_argument("--disabled", action="store_true")

    del_perm = sub.add_parser("remove-row-permission", help="Delete a row permission.")
    del_perm.add_argument("--group", required=True)
    del_perm.add_argument("--dataset-id", default="*")
    del_perm.add_argument("--table", required=True)
    del_perm.add_argument("--column", required=True)
    del_perm.add_argument("--operator", default="=")
    del_perm.add_argument("--value", required=True)

    args = parser.parse_args()

    if args.command == "init":
        ensure_auth_db()
    elif args.command == "upsert-user":
        upsert_user(args.username, args.password, args.role, not args.disabled)
    elif args.command == "disable-user":
        set_user_enabled(args.username, False)
    elif args.command == "enable-user":
        set_user_enabled(args.username, True)
    elif args.command == "upsert-group":
        upsert_permission_group(args.name, args.description, not args.disabled)
    elif args.command == "bind-group":
        bind_user_group(args.username, args.group, not args.disabled)
    elif args.command == "add-row-permission":
        add_row_permission(args.group, args.dataset_id, args.table, args.column, args.value, args.operator, not args.disabled)
    elif args.command == "remove-row-permission":
        removed = remove_row_permission(args.group, args.dataset_id, args.table, args.column, args.value, args.operator)
        print(f"removed={removed}")
        return
    print(f"auth_db={auth_db_path()}")


if __name__ == "__main__":
    main()
