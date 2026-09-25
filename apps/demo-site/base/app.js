const STORAGE_TODOS = "agentqa_todos";
const STORAGE_USER = "agentqa_user";

function getTodos() {
  return JSON.parse(localStorage.getItem(STORAGE_TODOS) || "[]");
}

function renderTodos() {
  const list = document.getElementById("todo-list");
  if (!list) return;
  list.innerHTML = "";
  for (const item of getTodos()) {
    const li = document.createElement("li");
    li.textContent = item;
    li.addEventListener("click", () => li.classList.toggle("done"));
    list.appendChild(li);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const loginForm = document.getElementById("login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", (event) => {
      event.preventDefault();
      localStorage.setItem(STORAGE_USER, document.getElementById("username").value);
      window.location.href = "index.html";
    });
  }
  const addBtn = document.getElementById("add-btn");
  if (addBtn) {
    if (!localStorage.getItem(STORAGE_USER)) {
      window.location.href = "login.html";
      return;
    }
    const input = document.getElementById("new-todo");
    document.getElementById("greeting").textContent = "Xin chào " + localStorage.getItem(STORAGE_USER);
    addBtn.addEventListener("click", () => {
      const value = input.value.trim();
      if (!value) return;
      const todos = getTodos();
      todos.push(value);
      localStorage.setItem(STORAGE_TODOS, JSON.stringify(todos));
      input.value = "";
      renderTodos();
    });
    renderTodos();
  }
});
