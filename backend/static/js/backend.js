// ============================================================
// BACKEND GENERATION
// ============================================================

const backendBtn =
    document.getElementById("backendBtn");

if (backendBtn) {

    backendBtn.addEventListener(
        "click",
        async () => {

            // ========================================
            // VALIDATION
            // ========================================

            if (!window.latestRequirements) {

                alert("Requirements are missing.");

                return;
            }

            if (!window.latestArchitecture) {

                alert("Architecture is missing.");

                return;
            }

            if (!window.latestDatabase) {

                alert("Database Design is missing.");

                return;
            }

            // ========================================
            // UI ELEMENTS
            // ========================================

            const backendOutput =
                document.getElementById(
                    "backendOutput"
                );

            const backendStructure =
                document.getElementById(
                    "backendStructure"
                );

            backendOutput.innerHTML =
                "<h3>⏳ Generating Backend Structure...</h3>";

            backendBtn.disabled = true;

            try {

                // ====================================
                // API CALL
                // ====================================

                const response =
                    await fetch(
                        "/api/backend",
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body: JSON.stringify({

                                requirements:
                                    window.latestRequirements,

                                architecture:
                                    window.latestArchitecture,

                                database:
                                    window.latestDatabase

                            })

                        }
                    );

                const data =
                    await response.json();

                console.log(
                    "Backend Response:",
                    data
                );

                // ====================================
                // HANDLE FAILURE
                // ====================================

                if (
                    !response.ok ||
                    !data.success
                ) {

                    backendOutput.innerHTML = `
                        <span style="color:red;">
                            ${
                                data.message ||
                                "Backend Generation Failed"
                            }
                        </span>
                    `;

                    return;
                }

                // ====================================
                // SUCCESS
                // ====================================

                const backend =
                    data.backend;

                window.latestBackend =
                    backend;

                backendOutput.innerHTML =
                    "<h3>✅ Backend Structure Generated Successfully</h3>";

                // ====================================
                // DISPLAY STRUCTURE
                // ====================================

                backendStructure.textContent =
                    backend.structure ||
                    "No backend structure generated.";

                // ====================================
                // ENABLE FRONTEND STAGE
                // ====================================

                const frontendBtn =
                    document.getElementById(
                        "frontendBtn"
                    );

                if (frontendBtn) {

                    frontendBtn.disabled =
                        false;
                }

                const frontendOutput =
                    document.getElementById(
                        "frontendOutput"
                    );

                if (frontendOutput) {

                    frontendOutput.innerHTML =
                        "✅ Backend Design Completed. Frontend Generation can begin.";
                }

                console.log(
                    "Backend Structure Generated Successfully"
                );

            }

            catch (error) {

                console.error(
                    "Backend Error:",
                    error
                );

                backendOutput.innerHTML = `
                    <span style="color:red;">
                        Backend Generation Failed.
                        Check Flask Terminal.
                    </span>
                `;
            }

            finally {

                backendBtn.disabled = false;
            }
        }
    );
}