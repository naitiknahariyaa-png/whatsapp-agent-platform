import React, { useEffect, useState } from "react";
import {
  Button, Table, TableBody, TableCell, TableHead, TableRow,
  Typography, Alert, Box, Chip, Stack,
} from "@mui/material";
import { api } from "../api";
import { useAuth } from "../auth";

interface ApprovalItem {
  id: string;
  action_type: string;
  client_id: number;
  amount: number | null;
  payload: Record<string, unknown>;
  created_by: string;
  created_at: string;
  expires_at: string | null;
  risk: string | null;
}

export default function Approvals() {
  const { token } = useAuth();
  const [items, setItems] = useState<ApprovalItem[]>([]);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setErr(null);
    try {
      const data = await api<{ pending: ApprovalItem[] }>("/api/approvals/pending", {}, token);
      setItems(data.pending);
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Failed to load approvals");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function decide(id: string, approve: boolean) {
    setErr(null);
    try {
      await api<{ request_id: string }>(`/api/approvals/${id}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision: approve ? "approved" : "rejected", comment: "" }),
      }, token);
      await load();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Decision failed");
    }
  }

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2 }}>Pending Approvals</Typography>
      {err && <Alert severity="error" sx={{ mb: 2 }}>{err}</Alert>}
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>ID</TableCell>
            <TableCell>Action</TableCell>
            <TableCell>Amount</TableCell>
            <TableCell>Risk</TableCell>
            <TableCell>Created</TableCell>
            <TableCell>Decide</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {items.length === 0 && (
            <TableRow><TableCell colSpan={6}>No pending approvals.</TableCell></TableRow>
          )}
          {items.map((a) => (
            <TableRow key={a.id}>
              <TableCell>{a.id.slice(0, 8)}…</TableCell>
              <TableCell>{a.action_type}</TableCell>
              <TableCell>{a.amount ?? "—"}</TableCell>
              <TableCell><Chip size="small" label={a.risk ?? "—"} /></TableCell>
              <TableCell>{new Date(a.created_at).toLocaleString()}</TableCell>
              <TableCell>
                <Stack direction="row" spacing={1}>
                  <Button size="small" variant="contained" color="success"
                    onClick={() => decide(a.id, true)}>Approve</Button>
                  <Button size="small" variant="outlined" color="error"
                    onClick={() => decide(a.id, false)}>Reject</Button>
                </Stack>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}