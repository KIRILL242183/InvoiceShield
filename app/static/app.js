'use strict';
const invoiceForm = document.getElementById('invoice-form-submit');
if (invoiceForm) {
  invoiceForm.addEventListener('submit', (event) => {
    if (invoiceForm.dataset.submitted === 'yes') {
      event.preventDefault();
      return;
    }
    invoiceForm.dataset.submitted = 'yes';
    const button = invoiceForm.querySelector('button[type="submit"]');
    if (button) {
      button.disabled = true;
      button.textContent = 'Проверяем…';
    }
  });
}
const supplier = document.getElementById('supplier-select');
const bank = document.getElementById('bank-account');
if (supplier && bank) {
  supplier.addEventListener('change', () => {
    bank.value = supplier.selectedOptions[0]?.dataset.bank || '';
  });
}
