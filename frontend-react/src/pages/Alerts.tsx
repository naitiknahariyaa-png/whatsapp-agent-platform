import React, { useEffect, useState } from "react";
import {
  Button, Table, TableBody, TableCell, TableHead, TableRow,
  Typography, Alert, Box, Chip,
} from "@mui/material";
import { api } from "../api";
import { useAuth } from "../auth";

interface AlertItem {
  name: string;
  severity: string;
  message: string;
  details: Record<string, unknown>;
  timestamp: string;
}

export default function Alerts() {
  const { token } = useAuth();
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setErr(null);
    try {
      const data = await api<{ alerts: AlertItem[] }>("/alerts", {}, token);
      setAlerts(data.alerts);
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Failed to load alerts");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function trigger() {
    setErr(null);
    try {
      const data = await api<{ alerts: AlertItem[] }>("/alerts/trigger", {
        method: "POST",
        body: JSON.stringify({ name: "all" }),
      }, token);
      setAlerts(data.alerts);
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Trigger failed");
    }
  }

  const color = (s: string) =>
    s === "critical" ? "error" : s === "warning" ? "warning" : "info";

  return (
    <Box>
      <Box sx={{ display: "flex", justifyContent: "space-between", mb: 2 }}>
        <Typography variant="h6">System Alerts</Typography>
        <Button variant="contained" onClick={trigger}>Run checks now</Button>
      </Box>
      {err && <Alert severity="error" sx={{ mb: 2 }}>{err}</Alert>}
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Severity</TableCell>
            <TableCell>Name</TableCell>
            <TableCell>Message</TableCell>
            <TableCell>Time</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {alerts.length === 0 && (
            <TableRow><TableCell colSpan={4}>No active alerts.</TableCell></TableRow>
          )}
          {alerts.map((a) => (
            <TableRow key={a.name + a.timestamp}>
              <TableCell><Chip size="small" color={color(a.severity) as never} label={a.severity} /></TableCell>
              <TableCell>{a.name}</TableCell>
              <TableCell>{a.message}</TableCell>
              <TableCell>{new Date(a.timestamp).toLocaleString()}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}