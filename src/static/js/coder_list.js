$(function() {
  $('#coder-list .add-account').click(function() {
    clear_tooltip()
    event.preventDefault()

    $('<input>').attr({
      type: 'hidden',
      name: 'group_id',
      value: $(this).attr('data-group-id'),
    }).appendTo(
      $('#coder-list').closest('form')
    )

    $(this).closest('td').append($('#add-list-value'))
    $('#add-list-value-coder').remove()
    $(this).remove()
  })

  $('#coder-list .edit-group').click(function() {
    clear_tooltip()
    event.preventDefault()
    $(this).closest('td').find('[name="delete_value_id"]').toggleClass('hidden')
    $(this).closest('td').find('[name="delete_group_id"]').toggleClass('hidden')
    $(this).remove()
  })

  $('#raw-value').on('change keyup paste', function() {
    $('#raw-submit').attr('disabled', !$(this).val())
  })

  $('.edit-name').editable({
    params: function(params) {
      params.group_id = $(this).data('group-id')
      return params
    }
  })
})
