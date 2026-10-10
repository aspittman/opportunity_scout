// Form feedback only; core workflows also work without JavaScript.
document.addEventListener('submit', (event) => {
  const button = event.target.querySelector('button[type="submit"], button:not([type])');
  if (button) {
    button.disabled = true;
    button.textContent = 'Saving…';
  }
});
