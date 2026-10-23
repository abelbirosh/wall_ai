import express from "express";
import { fetchProducts } from "./catalogClient";
import { sendEmail } from "./email";

const app = express();
app.use(express.json());

app.post("/notify", async (req, res) => {
  await sendEmail(req.body.to, req.body.message);
  res.json({ ok: true });
});

app.get("/digest", async (_req, res) => {
  const products = await fetchProducts();
  res.json({ count: products.length });
});

app.listen(3000);
