$(function() {
  $('#contest').on('change', function() {
    var contest = $(this).val()
    $('button[value="start"]').attr('disabled', !contest)
  })
})
