import { useEffect, useState } from "react";
import { UsersService } from "@/client";
import Button from "./Button";
import { formatError } from "@/utils";

function handleRefresh() {
  window.location.reload();
}

export function UserList() {
  const [users, setUsers] = useState([]);
  useEffect(() => {
    const onError = formatError.bind(null);
    UsersService.readUsers()
      .then((r) => setUsers(r.data))
      .catch(onError);
  }, []);
  return (
    <ul>
      {users.length}
      <Button onClick={handleRefresh} />
    </ul>
  );
}

export function UnusedWidget() {
  // Never rendered: the model should flag it.
  return <div />;
}
