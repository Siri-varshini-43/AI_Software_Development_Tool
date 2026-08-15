// Global variable shared across all JS files
window.latestRequirements = "";

const analyzeBtn = document.getElementById("analyzeBtn");
const output = document.getElementById("requirementsOutput");
const editBtn = document.getElementById("editBtn");
const saveBtn = document.getElementById("saveBtn");
const cancelBtn = document.getElementById("cancelBtn");

analyzeBtn.addEventListener("click", async () => {

    const prompt = document.getElementById("prompt").value;

    if (prompt.trim() === "") {

        alert("Enter Project Description");
        return;

    }

    output.value = "Generating Requirements...";

    try {

        const response = await fetch("/api/requirements", {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                prompt: prompt
            })

        });

        const data = await response.json();

        if (data.success) {

            // Save globally
            window.latestRequirements = data.requirements;

            output.value = window.latestRequirements;

        }
        else {

            output.value = data.message;

        }

    }
    catch (error) {

        console.log(error);

        output.value = "Server Error";

    }

});


editBtn.addEventListener("click", () => {

    output.removeAttribute("readonly");

    output.focus();

    output.style.border = "2px solid #007bff";

    editBtn.style.display = "none";
    saveBtn.style.display = "inline-block";
    cancelBtn.style.display = "inline-block";

});


saveBtn.addEventListener("click", () => {

    // Save edited requirements globally
    window.latestRequirements = output.value;

    output.setAttribute("readonly", true);

    output.style.border = "1px solid gray";

    editBtn.style.display = "inline-block";
    saveBtn.style.display = "none";
    cancelBtn.style.display = "none";

    alert("Requirements Saved Successfully");

});


cancelBtn.addEventListener("click", () => {

    // Restore last saved version
    output.value = window.latestRequirements;

    output.setAttribute("readonly", true);

    output.style.border = "1px solid gray";

    editBtn.style.display = "inline-block";
    saveBtn.style.display = "none";
    cancelBtn.style.display = "none";

});