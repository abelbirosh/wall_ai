import { useEffect, useState } from "react";
import { UsersService } from "@/client";
import { Button } from "./Button";

function handleRefresh() {
  window.location.reload();
}

export function UserList() {
  const [users, setUsers] = useState([]);
  useEffect(() => {
    UsersService.readUsers().then((r) => setUsers(r.data));
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
