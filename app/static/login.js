async function login(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const status = document.getElementById("loginStatus");
  status.textContent = "正在登录...";
  const payload = {
    username: form.username.value.trim(),
    password: form.password.value,
  };
  const response = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    status.textContent = "用户名或密码错误";
    return;
  }
  window.location.href = "/";
}

document.getElementById("loginForm").addEventListener("submit", (event) => {
  login(event).catch((error) => {
    document.getElementById("loginStatus").textContent = error.message;
  });
});
