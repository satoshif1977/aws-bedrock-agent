output "lambda_function_url" {
  description = "Lambda Function URL（Slack の Webhook URL に設定する）"
  value       = aws_lambda_function_url.main.function_url
}

output "lambda_function_name" {
  description = "Lambda 関数名"
  value       = aws_lambda_function.main.function_name
}

output "lambda_log_group" {
  description = "CloudWatch Logs グループ名"
  value       = aws_cloudwatch_log_group.lambda.name
}

output "cloudwatch_logs_url" {
  description = "CloudWatch Logs コンソール URL"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#logsV2:log-groups/log-group/${replace(aws_cloudwatch_log_group.lambda.name, "/", "$252F")}"
}
