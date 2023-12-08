$(function() {
  $('a[data-service]').click(function(event) {
      event.preventDefault()
      var $form = $(this).closest('form')
      var $service = $form.find('[name="service"]')
      $service.val($(this).data('service'))
      $form.submit()
  })

  $('#session_duration').select2({
      width: '100%',
      minimumResultsForSearch: -1,
  })
})
