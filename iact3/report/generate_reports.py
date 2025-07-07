import asyncio
import datetime
import json
import xml.dom.minidom as minidom
import logging
import os
import textwrap
import time
from pathlib import Path

import aiofiles
import tabulate
import yattag

from iact3.stack import Stacker, Stack

LOG = logging.getLogger(__name__)


class ReportBuilder:
    """
    This class generates the test report.
    """

    def __init__(self, stacks: Stacker, output_file: Path):
        self._stacks = stacks
        self._output_file = output_file
        self._report_json_name = f'{self._stacks.project_name}-result.json'

    async def generate_report(self):
        doc = yattag.Doc()

        tag = doc.tag
        text = doc.text
        dirname = os.path.abspath(os.path.dirname(__file__))
        details = []
        test_result = 'Success'
        async with aiofiles.open(f'{dirname}/html.css', 'r') as f:
            output_css = await f.read()

        with tag("html"):
            with tag("head"):
                doc.stag("meta", charset="utf-8")
                doc.stag("meta", name="viewport", content="width=device-width")
                with tag("style", type="text/css"):
                    text(output_css)
                with tag("title"):
                    text("Iact3 Report")

            with tag("body"):
                tested_on = time.strftime("%A - %b,%d,%Y @ %H:%M:%S")

                with tag("table", "class=header-table-fill"):
                    with tag("tbody"):
                        with tag("th", "colspan=2"):
                            with tag("tr"):
                                with tag("td"):
                                    text("Tested on: ")
                                    text(tested_on)
            doc.stag("p")
            with tag("table", "class=table-fill"):
                with tag("tbody"):
                    with tag("thread"):
                        with tag("tr"):
                            with tag("th", "class=text-center", "width=25%"):
                                text("Test Name")
                            with tag("th", "class=text-left", "width=10%"):
                                text("Tested Region")
                            with tag("th", "class=text-left", "width=30%"):
                                text("Stack Name")
                            with tag("th", "class=text-left", "width=20%"):
                                text("Tested Results")
                            with tag("th", "class=text-left", "width=15%"):
                                text("Test Logs")

                            for stack in self._stacks.stacks:
                                with tag("tr", "class= test-footer"):
                                    with tag("td", "colspan=5"):
                                        text("")

                                LOG.info(f'Start producing test reports for {stack.test_name} in {stack.region}...')
                                test_name = stack.test_name
                                status = stack.status
                                stack_name = stack.name
                                region = stack.region
                                stack_id = stack.id
                                css = "class=test-green" if status == 'CREATE_COMPLETE' else 'class=test-red'

                                with tag("tr"):
                                    with tag("td", "class=test-info"):
                                        with tag("h3"):
                                            text(test_name)
                                    with tag("td", "class=text-left"):
                                        text(region)
                                    with tag("td", "class=text-left"):
                                        ref_url = f"https://ros.console.aliyun.com/{region}/stacks/{stack_id}"
                                        with tag("a", href=ref_url):
                                            text(stack_name)
                                    with tag("td", css):
                                        text(str(status))
                                    with tag("td", "class=text-left"):
                                        clog = f"{stack_name}-{region}.txt"
                                        with tag("a", href=clog):
                                            text("View Logs ")
                                success = stack.launch_succeeded
                                if not success:
                                    test_result = 'Failed'
                                details.append({
                                    'TestName': test_name,
                                    'TestedRegion': region,
                                    'StackName': stack_name,
                                    'StackId': stack.id,
                                    'TestResult': status,
                                    'TestLog': clog,
                                    'Result': 'Success' if success else 'Failed'
                                })
                        doc.stag("p")

            html_output = yattag.indent(
                doc.getvalue(), indentation="    ", newline="\r\n", indent_text=True
            )
            with open(str(self._output_file / 'index.html'), 'w', encoding='utf-8') as _f:
                _f.write(html_output)
            json_result = {
                'Result': test_result,
                'Details': details
            }
            file_name = self._report_json_name
            with open(str(self._output_file / file_name), 'w', encoding='utf-8') as f:
                json.dump(json_result, f, ensure_ascii=False)
            LOG.info(f'The test report has been completed, you can view it in {self._output_file} directory.')
            return html_output

    @staticmethod
    async def get_events(stack: Stack):
        stack_events = await stack.events(refresh=True)
        events = []
        for event in stack_events:
            event_details = {
                "TimeStamp": str(event.timestamp),
                "ResourceStatus": event.status,
                "ResourceType": event.type,
                "LogicalResourceId": event.logical_id,
            }
            if event.status_reason:
                event_details["ResourceStatusReason"] = event.status_reason
            else:
                event_details["ResourceStatusReason"] = ""

            events.append(event_details)
        return events

    @staticmethod
    async def get_resources(stack: Stack):
        stack_resources = await stack.resources(refresh=True)
        resources = []
        for resource in stack_resources:
            resource_details = {
                "TimeStamp": str(resource.last_updated_timestamp),
                "ResourceStatus": resource.status,
                "ResourceType": resource.type,
                "LogicalResourceId": resource.logical_id,
                "PhysicalResourceId": resource.physical_id
            }
            if resource.status_reason:
                resource_details["ResourceStatusReason"] = resource.status_reason
            else:
                resource_details["ResourceStatusReason"] = ""
            resources.append(resource_details)
        return resources

    @staticmethod
    async def get_outputs(stack: Stack):
        outputs = [
            {
                "OutputKey": o["OutputKey"],
                "OutputValue": o.get("OutputValue"),
                "Description": o.get("Description")
            } for o in stack.outputs or []
        ]
        return outputs

    @staticmethod
    async def get_hook_result(stack: Stack):
        return [
            {
                "HookName": h["HookName"],
                "ExecuteStatus": h["ExecuteStatus"],
                "ResultFileName": h["ResultFileName"],
                "OSSLocation": h.get("OSSLocation"),
            } for h in stack.hook_results or []
        ]


    async def create_logs(self, log_format:str):
        if log_format:
            log_formats = log_format.split(',')
        else:
            log_formats = []
        tasks = []
        file_names = []
        for stack in self._stacks.stacks:
            file_name = f'{stack.name}-{stack.region}'
            task = asyncio.create_task(self.write_logs(stack, self._output_file / file_name, log_formats))
            tasks.append(task)
            file_names.append(file_name + ".txt")
            if "json" in log_formats:
                file_names.append(file_name + ".json")
            if "xml" in log_formats:
                file_names.append(file_name + ".xml")
        await asyncio.gather(*tasks)
        file_names.append(self._report_json_name)
        return file_names

    async def add_attr_minidom(self, doc: minidom.Document,father_node: minidom.Element, label, value):     
        child = doc.createElement(label)
        father_node.appendChild(child)
        if isinstance(value, dict):
            for k, v in value.items():
                await self.add_attr_minidom(doc, child, k, v)
            
        elif isinstance(value, list):
            for list_item in value:
                await self.add_attr_minidom(doc, child, "item", list_item)
        else:
            child_content = doc.createTextNode(str(value))
            child.appendChild(child_content)
       
    async def write_logs(self, stack: Stack, log_path: Path, log_formats: list):
        stack_name = stack.name
        region = stack.region
        stack_id = stack.id or ''
        parameters = stack.parameters

        events = await self.get_events(stack) if stack.id else []
        resources = await self.get_resources(stack) if stack.id else []
        outputs = await self.get_outputs(stack) if stack.id else []
        hook_results = await self.get_hook_result(stack) if stack.id else []

        if stack.launch_succeeded:
            tested_result = 'Success'
            reason = 'Stack launch was successful'
        else:
            tested_result = 'Failed'
            reason = f'{stack.status}, {stack.status_reason}'

        test_time = datetime.datetime.now().strftime("%A, %d. %B %Y %I:%M%p")

        if "json" in log_formats:
            with open(str(log_path) + '.json', 'w', encoding='utf-8') as log_output:
                json_output = {
                    "Region": region,
                    "StackName": stack_name,
                    "StackId": stack_id,
                    "Parameters": parameters,
                    "TestedResult": tested_result,
                    "ResultReason": str(reason),
                    "Events": events,
                    "Resources": resources,
                    "TestTime": test_time,
                    "Outputs": outputs,
                    "HookLogs": hook_results
                }
                json.dump(json_output, log_output, ensure_ascii=False, indent=4)
                log_output.close()
        
        if "xml" in log_formats:
            with open(str(log_path)+'.xml', 'w', encoding='utf-8') as log_output:
                xml_doc = minidom.Document()
                root = xml_doc.createElement(f'{stack.name}-{stack.region}')
                xml_doc.appendChild(root)

                await self.add_attr_minidom(xml_doc, root, "Region", region)
                await self.add_attr_minidom(xml_doc, root, "StackName", stack_name)
                await self.add_attr_minidom(xml_doc, root, "StackId", stack_id)
                await self.add_attr_minidom(xml_doc, root, "Parameters", parameters)
                await self.add_attr_minidom(xml_doc, root, "TestedResult", tested_result)
                await self.add_attr_minidom(xml_doc, root, "ResultReason", reason)
                await self.add_attr_minidom(xml_doc, root, "Events", events)
                await self.add_attr_minidom(xml_doc, root, "Resources", resources)
                await self.add_attr_minidom(xml_doc, root, "TestTime", test_time)
                await self.add_attr_minidom(xml_doc, root, "Outputs", outputs)
                await self.add_attr_minidom(xml_doc, root, "HookLogs", hook_results)
            
                log_output.write(xml_doc.toprettyxml(indent="\t"))

        async with aiofiles.open(str(log_path)+'.txt', "a", encoding="utf-8") as log_output:
            await log_output.write(
                "------------------------------------------------------------------"
                "-----------\n"
            )
            line_flag = "*"*77
            line_flag = f"{line_flag}\n"
            await log_output.write("Region: " + region + "\n")
            await log_output.write("StackName: " + stack_name + "\n")
            await log_output.write("StackId: " + stack_id + "\n")
            await log_output.write(line_flag)
            if parameters:
                parameters = [
                    dict(
                        ParameterKey=k,
                        ParameterValue=v if v is not None else ''
                    ) for k, v in parameters.items()
                ]
                await log_output.write(tabulate.tabulate(parameters, headers="keys"))
                await log_output.write(f"\n{line_flag}")
            await log_output.write(f"TestedResult: {tested_result}  \n")
            await log_output.write("ResultReason:  \n")
            await log_output.write(textwrap.fill(str(reason), 85) + "\n")
            await log_output.write(line_flag)
            await log_output.write(line_flag)
            await log_output.write("Events:  \n")
            await log_output.writelines(tabulate.tabulate(events, headers="keys"))
            await log_output.write(f"\n{line_flag}")
            await log_output.write(line_flag)
            await log_output.write("Resources:  \n")
            await log_output.write(tabulate.tabulate(resources, headers="keys"))
            await log_output.write(f"\n{line_flag}")
            await log_output.write(line_flag)
            await log_output.write("Outputs:  \n")
            await log_output.write(tabulate.tabulate(outputs, headers="keys"))
            await log_output.write(f"\n{line_flag}")
            await log_output.write(line_flag)
            await log_output.write("HookLogs:  \n")
            await log_output.write(tabulate.tabulate(hook_results, headers="keys"))
            await log_output.write(f"\n{line_flag}")
            await log_output.write(line_flag)
            await log_output.write(
                "Tested on: "
                + test_time
                + "\n"
            )
            await log_output.write(
                "------------------------------------------------------------------"
                "-----------\n\n"
            )
            await log_output.close()
