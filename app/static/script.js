document.getElementById("uploadBtn").addEventListener("click", async () => {
  const file = document.getElementById("pdfFile").files[0];
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch("/upload_pdf", { method: "POST", body: formData });
  alert(await res.text());
});

document.getElementById("queryForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = document.getElementById("query").value;
  const res = await fetch("/query", {
    method: "POST",
    body: new URLSearchParams({ query })
  });
  const data = await res.json();
  document.getElementById("response").innerText = data.answer;
});
