let unsavedChanges = false;

document.querySelector("input").addEventListener("input", function () {
    unsavedChanges = true;
});

window.addEventListener('beforeunload', function (event) {
    // Customize the message shown in the confirmation dialog
    const message = "Are you sure you want to navigate away? You may lose your changes.";
    event.preventDefault();
    event.returnValue = message; // Required for most browsers
    return message;
});