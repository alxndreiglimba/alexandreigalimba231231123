const toast = document.getElementById("toast");

function showToast(message) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 2200);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    document.querySelectorAll(".panel").forEach((panel) => panel.classList.add("hidden"));
    document.getElementById("panel-" + button.dataset.tab).classList.remove("hidden");
  });
});

async function loadStats() {
  const stats = await api("/api/stats");
  document.getElementById("stats").innerHTML = `
    <div class="stat"><span>Students</span><strong>${stats.students}</strong></div>
    <div class="stat"><span>Events</span><strong>${stats.events}</strong></div>
    <div class="stat"><span>Open sanctions</span><strong>${stats.unpaid}</strong></div>
    <div class="stat"><span>Unpaid total</span><strong>${Number(stats.unpaid_total).toFixed(2)}</strong></div>
  `;
}

async function loadStudents() {
  const students = await api("/api/students");
  document.getElementById("student-list").innerHTML = students.length
    ? students.map((student) => `
        <article class="item">
          <h3>${student.full_name}</h3>
          <p class="meta">${student.student_id} · ${student.course || "No course"}</p>
          <div class="actions">
            <button class="ghost small danger" data-del-student="${student.id}">Remove</button>
          </div>
        </article>
      `).join("")
    : "<p class='lede'>No students yet.</p>";
}

async function loadEvents() {
  const events = await api("/api/events");
  document.getElementById("event-list").innerHTML = events.length
    ? events.map((event) => `
        <article class="item">
          <h3>${event.title}</h3>
          <p class="meta">${event.event_date} · ${event.location || "No location"} · Present ${event.present_count || 0} · Absent ${event.absent_count || 0}</p>
          <div class="actions">
            <button class="small" data-open-event="${event.id}">Take attendance</button>
            <button class="ghost small danger" data-del-event="${event.id}">Delete</button>
          </div>
        </article>
      `).join("")
    : "<p class='lede'>No events yet. Create one to start taking attendance.</p>";
}

async function loadSanctions() {
  const sanctions = await api("/api/sanctions");
  document.getElementById("sanction-list").innerHTML = sanctions.length
    ? sanctions.map((row) => `
        <article class="item">
          <h3>${row.full_name} <span class="pill ${row.status}">${row.status}</span></h3>
          <p class="meta">${row.student_id} missed ${row.event_title} on ${row.event_date}</p>
          <div class="amount-row">
            <input type="number" min="0" step="0.01" value="${row.amount}" data-amount="${row.id}" />
            <input type="text" value="${row.owner_note || ""}" placeholder="Owner note" data-note="${row.id}" />
            <button class="small" data-save-sanction="${row.id}">Save amount</button>
            ${row.status !== "paid" ? `<button class="small" data-pay-sanction="${row.id}">Mark paid</button>` : ""}
          </div>
        </article>
      `).join("")
    : "<p class='lede'>No sanctions. Mark a student absent on an event to create one.</p>";
}

async function openAttendance(eventId) {
  const data = await api("/api/events/" + eventId + "/attendance");
  document.getElementById("attendance-box").classList.remove("hidden");
  document.getElementById("attendance-title").textContent = data.event.title;
  document.getElementById("attendance-meta").textContent =
    data.event.event_date + (data.event.location ? " · " + data.event.location : "");
  document.getElementById("attendance-list").innerHTML = data.students.length
    ? data.students.map((student) => `
        <article class="item">
          <h3>${student.full_name} ${student.attendance_status ? `<span class="pill ${student.attendance_status}">${student.attendance_status}</span>` : ""}</h3>
          <p class="meta">${student.student_id} · ${student.course || "No course"}</p>
          <div class="actions">
            <button class="small" data-mark="${student.id}" data-event="${eventId}" data-status="present">Present</button>
            <button class="small danger" data-mark="${student.id}" data-event="${eventId}" data-status="absent">Absent / sanction</button>
          </div>
        </article>
      `).join("")
    : "<p class='lede'>Add students first, then mark attendance here.</p>";
}

document.getElementById("student-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("/api/students", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    form.reset();
    showToast("Student saved");
    await refresh();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("event-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("/api/events", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    form.reset();
    showToast("Event saved");
    await refresh();
  } catch (error) {
    showToast(error.message);
  }
});

document.body.addEventListener("click", async (event) => {
  const target = event.target;
  try {
    if (target.dataset.delStudent) {
      await api("/api/students/" + target.dataset.delStudent, { method: "DELETE" });
      showToast("Student removed");
      await refresh();
    }
    if (target.dataset.delEvent) {
      await api("/api/events/" + target.dataset.delEvent, { method: "DELETE" });
      showToast("Event deleted");
      document.getElementById("attendance-box").classList.add("hidden");
      await refresh();
    }
    if (target.dataset.openEvent) {
      await openAttendance(target.dataset.openEvent);
    }
    if (target.id === "close-attendance") {
      document.getElementById("attendance-box").classList.add("hidden");
    }
    if (target.dataset.mark) {
      await api("/api/events/" + target.dataset.event + "/attendance", {
        method: "POST",
        body: JSON.stringify({
          student_pk: Number(target.dataset.mark),
          status: target.dataset.status,
        }),
      });
      showToast(target.dataset.status === "absent" ? "Marked absent — sanction created" : "Marked present");
      await openAttendance(target.dataset.event);
      await refresh();
    }
    if (target.dataset.saveSanction) {
      const id = target.dataset.saveSanction;
      const amount = document.querySelector(`[data-amount="${id}"]`).value;
      const owner_note = document.querySelector(`[data-note="${id}"]`).value;
      await api("/api/sanctions/" + id, {
        method: "POST",
        body: JSON.stringify({ amount, owner_note, status: "set" }),
      });
      showToast("Sanction amount saved");
      await refresh();
    }
    if (target.dataset.paySanction) {
      const id = target.dataset.paySanction;
      const amount = document.querySelector(`[data-amount="${id}"]`).value;
      await api("/api/sanctions/" + id, {
        method: "POST",
        body: JSON.stringify({ amount, status: "paid" }),
      });
      showToast("Marked as paid");
      await refresh();
    }
  } catch (error) {
    showToast(error.message);
  }
});

async function refresh() {
  await Promise.all([loadStats(), loadStudents(), loadEvents(), loadSanctions()]);
}

refresh();
