

$(function() {
  $('#coder-list .add-account').click(function() {
    event.preventDefault()

    $('<input>').attr({
      type: 'hidden',
      name: 'gid',
      value: $(this).attr('data-gid'),
    }).appendTo($('#coder-list').closest('form'))

    $(this).closest('td').append($('#add-list-value'))
    $('#add-list-value-coder').remove()
    $('#coder-list .add-account').remove()
  })

  $('#raw-value').on('change keyup paste', function() {
    $('#raw-submit').attr('disabled', !$(this).val())
  })
})
