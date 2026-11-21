const toast = document.getElementById("toast");
let currentAttendanceEventId = null;

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
    if (button.dataset.tab === "students") {
      Promise.all([loadEvents(), loadStats()])
        .then(() => loadStudents())
        .catch((error) => showToast(error.message));
    }
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

async function loadStudents(eventId = document.getElementById("roster-event-select").value) {
  let students;
  const meta = document.getElementById("roster-event-meta");
  if (eventId) {
    const data = await api(`/api/events/${eventId}/attendance`);
    students = data.students.filter((student) => student.attendance_status);
    meta.textContent = `${students.length} student${students.length === 1 ? "" : "s"} recorded for ${data.event.title}.`;
  } else {
    students = await api("/api/students");
    meta.textContent = "Showing all students in the roster.";
  }
  document.getElementById("student-list").innerHTML = students.length
    ? students.map((student) => `
        <article class="item">
          <h3>${student.full_name}${student.attendance_status ? ` <span class="pill ${student.attendance_status}">${student.attendance_status}</span>` : ""}</h3>
          <p class="meta">${student.student_id} · ${student.course || "No course"}${student.marked_at ? ` · Recorded ${student.marked_at}` : ""}</p>
          <div class="actions">
            <button class="ghost small danger" data-del-student="${student.id}">Remove</button>
          </div>
        </article>
      `).join("")
    : eventId
      ? "<p class='lede'>No attendance has been recorded for this event yet.</p>"
      : "<p class='lede'>No students yet. Import a student list to add students to the roster.</p>";
}

function updateRosterEventOptions(events) {
  const select = document.getElementById("roster-event-select");
  const selectedEventId = select.value;
  select.replaceChildren(new Option("All students", ""));
  events.forEach((event) => {
    select.add(new Option(`${event.title} · ${event.event_date}`, event.id));
  });
  if (events.some((event) => String(event.id) === selectedEventId)) {
    select.value = selectedEventId;
  } else {
    select.value = "";
  }
}

document.getElementById("roster-event-select").addEventListener("change", (event) => {
  loadStudents(event.currentTarget.value).catch((error) => showToast(error.message));
});

document.getElementById("student-import-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submitButton = form.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  try {
    const response = await fetch("/api/students/import", {
      method: "POST",
      body: new FormData(form),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || "Could not import student list.");
    }
    form.reset();
    document.getElementById("roster-event-select").value = "";
    showToast(`Import complete: ${data.added} added, ${data.updated} updated`);
    await Promise.all([loadStudents(), loadStats()]);
  } catch (error) {
    showToast(error.message);
  } finally {
    submitButton.disabled = false;
  }
});

async function loadEvents() {
  const events = await api("/api/events");
  updateRosterEventOptions(events);
  document.getElementById("event-list").innerHTML = events.length
    ? events.map((event) => `
        <article class="item">
          <h3>${event.title}</h3>
          <p class="meta">${event.event_date} · ${event.location || "No location"} · Present ${event.present_count || 0} · Absent ${event.absent_count || 0}</p>
          <p class="meta">${event.attendance_starts_at && event.attendance_cutoff_at
            ? `Check-in: ${event.attendance_starts_at.replace("T", " ")} – ${event.attendance_cutoff_at.replace("T", " ")}`
            : "Student check-in is not scheduled."}</p>
          <div class="actions">
            <button type="button" class="small" data-open-event="${event.id}">Take attendance</button>
            <a class="ghost small" href="/events/${event.id}/student-lookup" target="_blank" rel="noopener">Student look-up</a>
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
  currentAttendanceEventId = eventId;
  document.getElementById("attendance-box").classList.remove("hidden");
  document.getElementById("attendance-title").textContent = data.event.title;
  document.getElementById("attendance-meta").textContent =
    data.event.event_date +
    (data.event.location ? " · " + data.event.location : "") +
    (data.event.attendance_starts_at && data.event.attendance_cutoff_at
      ? ` · Check-in ${data.event.attendance_starts_at.replace("T", " ")} – ${data.event.attendance_cutoff_at.replace("T", " ")}`
      : "");
  const checkedInCount = data.students.filter(
    (student) => student.attendance_status === "present"
  ).length;
  document.getElementById("attendance-count").textContent =
    `${checkedInCount} of ${data.students.length} students marked present`;
  document.getElementById("attendance-list").innerHTML = data.students.length
    ? data.students.map((student) => `
        <article class="item">
          <h3>${student.full_name} ${student.attendance_status ? `<span class="pill ${student.attendance_status}">${student.attendance_status}</span>` : ""}</h3>
          <p class="meta">${student.student_id} · ${student.course || "No course"}${student.marked_at ? ` · Recorded ${student.marked_at}` : ""}</p>
          <div class="actions">
            <button class="small" data-mark="${student.id}" data-event="${eventId}" data-status="present">Present</button>
            <button class="small danger" data-mark="${student.id}" data-event="${eventId}" data-status="absent">Absent / sanction</button>
          </div>
        </article>
      `).join("")
    : "<p class='lede'>There are no students in the roster yet. Import a student list from the Students tab to start taking attendance.</p>";
}

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
  const target = event.target instanceof Element ? event.target.closest("button") : null;
  if (!target) return;
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
    if (target.id === "refresh-attendance" && currentAttendanceEventId) {
      await openAttendance(currentAttendanceEventId);
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
  await Promise.all([loadStats(), loadEvents(), loadSanctions()]);
  await loadStudents();
}

refresh();
