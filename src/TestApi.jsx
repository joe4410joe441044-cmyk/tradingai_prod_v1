import { useEffect, useState } from "react";

export default function TestApi() {
  const [data, setData] = useState("loading...");

  useEffect(() => {
    fetch("http://35.194.104.74:8000/price")
      .then(res => res.json())
      .then(res => {
        console.log("API OK:", res);
        setData(JSON.stringify(res));
      })
      .catch(err => {
        console.error("API ERROR:", err);
        setData("ERROR");
      });
  }, []);

  return (
    <div style={{ padding: 40 }}>
      <h1>TEST API</h1>
      <div>Result: {data}</div>
    </div>
  );
}