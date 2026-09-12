const elements = document.querySelectorAll('.fade-in');

function reveal() {
    const screenHeight = window.innerHeight;

    elements.forEach((el) => {
        const position = el.getBoundingClientRect().top;
        if (position < screenHeight - 100) {
            el.classList.add('show');
        }
    });
}

if (elements.length) {
    reveal();
    window.addEventListener('scroll', reveal);
}

function updateValue(slider) {
    const valueDisplay = slider.parentElement.querySelector('.value');
    const value = Number(slider.value);

    if (valueDisplay) {
        valueDisplay.textContent = value;
    }

    const percent = ((value - Number(slider.min)) / (Number(slider.max) - Number(slider.min))) * 100;
    slider.style.background = `linear-gradient(to right, #4facfe ${percent}%, #e2e8f0 ${percent}%)`;
}

document.querySelectorAll('input[type="range"]').forEach((slider) => {
    slider.addEventListener('input', () => updateValue(slider));
    updateValue(slider);
});

const steps = Array.from(document.querySelectorAll('.step'));
const progress = document.querySelector('.progress');
const backBtn = document.querySelector('.step-buttons .secondary');
const nextBtn = document.querySelector('.step-buttons .btn:not(.secondary)');
const submitBtn = document.querySelector('.submit-btn');
let currentStep = 0;

function updateButtons() {
    if (!backBtn || !nextBtn || !submitBtn) return;

    backBtn.style.display = currentStep === 0 ? 'none' : 'inline-block';
    nextBtn.style.display = currentStep === steps.length - 1 ? 'none' : 'inline-block';
    submitBtn.style.display = currentStep === steps.length - 1 ? 'inline-block' : 'none';
}

function updateProgress() {
    if (!progress || !steps.length) return;
    const percent = ((currentStep + 1) / steps.length) * 100;
    progress.style.width = `${percent}%`;
}

function showStep(index) {
    if (!steps.length) return;

    currentStep = Math.min(Math.max(index, 0), steps.length - 1);
    steps.forEach((step, i) => step.classList.toggle('active', i === currentStep));
    updateProgress();
    updateButtons();
}

function nextStep() {
    if (currentStep >= steps.length - 1) return;

    const currentInputs = steps[currentStep].querySelectorAll('input');
    const requiredMissing = Array.from(currentInputs).some((input) => {
        if (input.type === 'checkbox') return false;
        return input.hasAttribute('required') && input.value.trim() === '';
    });

    if (requiredMissing) {
        alert('Please fill in all required fields before continuing.');
        return;
    }

    showStep(currentStep + 1);
}

function prevStep() {
    if (currentStep > 0) {
        showStep(currentStep - 1);
    }
}

showStep(currentStep);

const scoreBars = document.querySelectorAll('.score-fill');
scoreBars.forEach((bar) => {
    const score = Number(bar.dataset.score || 0);
    requestAnimationFrame(() => {
        bar.style.width = `${score}%`;
    });
});