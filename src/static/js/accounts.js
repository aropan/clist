function init_account_buttons() {
  $('#accounts .add-account, #accounts .delete-account').click(function(e) {
    e.preventDefault()
    $btn = $(this)
    $btn.toggleClass('hidden')
    $loading = $(this).parent().find('.loading-account')
    $loading.toggleClass('hidden')
    $.ajax({
      type: 'POST',
      url: change_url,
      data: {
        pk: coder_pk,
        name: $btn.attr('data-action'),
        id: $btn.attr('data-id'),
      },
      success: function(data) {
        $btn.parent().children().toggleClass('hidden')
        $btn.toggleClass('hidden')
        $btn.closest('tr').toggleClass('info')
        notify($btn.attr('data-message'), 'success')
      },
      error: function(response) {
        if (response.responseJSON && response.responseJSON.message == 'redirect') {
            window.location.replace(response.responseJSON.url)
            return
        }
        $loading.toggleClass('hidden')
        $btn.toggleClass('hidden')
        log_ajax_error(response)
      },
    })
  })
}

function init_clickable_has_coders() {
  $('.has_coders.clickable').click(function(e) {
    var checkbox = $(this).next()
    checkbox.removeClass('hidden')
    checkbox.click()
    $(this).remove()
  })
}

function invert_accounts(e, s) {
  e.preventDefault()
  $('#accounts input[name="' + $.escapeSelector(s) + '"]').click()
}
