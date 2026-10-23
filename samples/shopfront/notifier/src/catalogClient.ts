import axios from "axios";

export async function fetchProducts() {
  const response = await axios.get("http://api:8000/products");
  return response.data;
}
