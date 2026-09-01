import React, { useState } from "react";
import { Box, Button, TextField, Typography, Alert, Paper } from "@mui/material";
import { useAuth } from "../auth";

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await login(email, password);
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box sx={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: "100vh" }}>
      <Paper sx={{ p: 4, width: 360 }} component="form" onSubmit={submit}>
        <Typography variant="h6" gutterBottom>
          Sign in
        </Typography>
        {err && <Alert severity="error" sx={{ mb: 2 }}>{err}</Alert>}
        <TextField label="Email" type="email" fullWidth margin="normal" required
          value={email} onChange={(e) => setEmail(e.target.value)} />
        <TextField label="Password" type="password" fullWidth margin="normal" required
          value={password} onChange={(e) => setPassword(e.target.value)} />
        <Button type="submit" variant="contained" fullWidth sx={{ mt: 2 }} disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </Paper>
    </Box>
  );
}