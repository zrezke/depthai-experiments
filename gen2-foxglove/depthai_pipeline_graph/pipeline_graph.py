#!/usr/bin/env python3
from argparse import ArgumentParser
import depthai as dai
import subprocess
import os
import signal
import re
import json
import time
from threading import Thread
from typing import Any, Dict, List


class NodePort:
    name: str
    type: int  # Input=3 / Output=0
    node_id: str
    group_name: str
    blocking: bool
    queue_size: int
    wait_for_message: bool

    def __str__(self):
        return f"- {self.name} ({self.type})"

    def __dict__(self):
        return {
            "name": self.name,
            "type": self.type,
            "node_id": self.node_id,
            "group_name": self.group_name,
            "blocking": self.blocking,
            "queue_size": self.queue_size,
            "wait_for_message": self.wait_for_message
        }


class Node:
    id: str
    name: str
    ports: List[NodePort]
    position: Dict[str, int] = None
    type: str = "pipelineNode"

    # def __str__(self):
    #     return f"(Node) ID: {self.id} NAME: {self.name}: PORTS: ({[str(port) for port in self.ports]})"

    def __str__(self):
        if self.position:
            return f"{self.name}: [x: {self.position['x']}, y: {self.position['y']}]"
        return f"{self.name}"

    def __dict__(self):
        return {
            "data": {
                "name": self.name,
                "ports": [port.__dict__() for port in self.ports],
            },
            "id": self.id,
            "position": self.position,
            "type": self.type
        }


class EdgeLabelOptions:
    label: str = None
    labelStyle: str = None
    labelShowBg: bool = None
    labelBgStyle: dict = None
    labelBgPadding: tuple[int, int] = None
    labelBgBorderRadius: int = None


class Edge(EdgeLabelOptions):
    id: str
    type: str = None
    source: str
    target: str
    sourceHandle: str = None
    targetHandle: str = None
    style: Dict = None
    animated: bool = None
    hidden: bool = None
    deletable: bool = None
    data: Dict = None
    className: str = None
    sourceNode: str = None
    targetNode: str = None
    selected: bool = None
    markerStart: str = None
    markerEnd: str = None
    zIndex: int = None
    ariaLabel: str = None
    interactionWidth: int = None
    focusable: bool = None


START_NODES = ['ColorCamera', 'MonoCamera', 'XLinkIn']


class PipelineGraph:
    node_color = {
        "ColorCamera": (241, 148, 138),
        "MonoCamera": (243, 243, 243),
        "ImageManip": (174, 214, 241),
        "VideoEncoder": (190, 190, 190),

        "NeuralNetwork": (171, 235, 198),
        "DetectionNetwork": (171, 235, 198),
        "MobileNetDetectionNetwork": (171, 235, 198),
        "MobileNetSpatialDetectionNetwork": (171, 235, 198),
        "YoloDetectionNetwork": (171, 235, 198),
        "YoloSpatialDetectionNetwork": (171, 235, 198),
        "SpatialDetectionNetwork": (171, 235, 198),

        "SPIIn": (242, 215, 213),
        "XLinkIn": (242, 215, 213),

        "SPIOut": (230, 176, 170),
        "XLinkOut": (230, 176, 170),

        "Script": (249, 231, 159),

        "StereoDepth": (215, 189, 226),
        "SpatialLocationCalculator": (215, 189, 226),

        "EdgeDetector": (248, 196, 113),
        "FeatureTracker": (248, 196, 113),
        "ObjectTracker": (248, 196, 113),
        "IMU": (248, 196, 113)
    }
    # For node types that does not appear in 'node_color'
    default_node_color = (190, 190, 190)
    process = None
    nodes: List[Node] = []

    def cmd_tool(self, args):
        os.environ["PYTHONUNBUFFERED"] = "1"
        os.environ["DEPTHAI_LEVEL"] = "debug"

        command = args.command.split()
        if args.use_variable_names:
            # If command starts with "python", we remove it
            if "python" in command[0]:
                command.pop(0)

            command = "python -m trace -t ".split() + command

        pipeline_create_re = f'.*:\s*(.*)\s*=\s*{args.pipeline_name}\.create.*'
        node_name = []
        self.process = subprocess.Popen(
            command, shell=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        schema_str = None
        record_output = ""  # Save the output and print it in case something went wrong
        while True:
            if self.process.poll() is not None:
                break
            line = self.process.stdout.readline()
            record_output += line
            if args.verbose:
                print(line.rstrip('\n'))
            # we are looking for  a line:  ... [debug] Schema dump: {"connections":[{"node1Id":1...
            match = re.match(r'.* Schema dump: (.*)', line)
            if match:
                schema_str = match.group(1)
                print("Pipeline schema retrieved")
                # break
                # TODO(themarpe) - expose "do kill" now
                # # print(schema_str)
                if not args.do_not_kill:
                    print("Terminating program...")
                    self.process.terminate()
            elif args.use_variable_names:
                match = re.match(pipeline_create_re, line)
                if match:
                    node_name.append(match.group(1))
        print("Program exited.")
        if schema_str is None:
            if not args.verbose:
                print(record_output)
            print("\nSomething went wrong, the schema could not be extracted")
            exit(1)
        schema = json.loads(schema_str)

        # print('Schema:', schema)
        self.transform_schema_to_reactflow(schema)

    def transform_schema_to_reactflow(self, schema):
        edges = []
        connections = schema['connections']
        nodes = schema['nodes']

        start_nodes: List[Node] = []

        reactflow_nodes = []

        for node_dict in nodes:
            node = Node()
            n = node_dict[1]
            node.id = str(n['id'])
            node.name = n["name"]
            node.ports = []
            for port_dict in n['ioInfo']:
                port = NodePort()
                port_info = port_dict[1]
                port.name = port_info['name']
                port.type = port_info['type']
                port.node_id = node.id
                port.group_name = port_info['group']
                port.blocking = port_info['blocking']
                port.queue_size = port_info['queueSize']
                port.wait_for_message = port_info['waitForMessage']
                node.ports.append(port)
            if node.name in START_NODES:
                start_nodes.append(node)
            else:
                self.nodes.append(node)

        col = 0
        row = 0
        current_column = start_nodes
        row_offset = 100
        col_offset = 200
        while current_column:
            # Get next column
            next_column = []
            for node in current_column:
                connections_from_node = [
                    str(connection["node2Id"]) for connection in connections if str(connection["node1Id"]) == node.id]
                next_column += filter(
                    lambda node: node.id in connections_from_node, self.nodes)

            corrected_next_column = []
            for node in next_column:
                all_connections_to_node = filter(
                    lambda conn: conn["node2Id"] == node.id, connections)
                if all(map(lambda conn: conn["node1Id"] in map(lambda x: x.id, current_column), all_connections_to_node)):
                    corrected_next_column.append(node)
            next_column = corrected_next_column

            # print([str(n) for n in current_column], "->", [str(n)
            #       for n in next_column])

            for node in current_column:
                if node not in reactflow_nodes:
                    print("Current column: ", node.name)
                    node.position = {"x": col *
                                     col_offset, "y": row * row_offset}
                    reactflow_nodes.append(node)
            # Now also set the position of the next col
            col += 1
            next_column_row = 0
            for next_col_node in next_column:
                if next_col_node not in reactflow_nodes:
                    print("Next column: ", next_col_node.name)
                    next_col_node.position = {"x": col * col_offset,
                                        "y": next_column_row * row_offset}
                    next_column_row += 1
                    reactflow_nodes.append(next_col_node)
            current_column = next_column
        # print("Reactflow: ", [str(n) for n in reactflow_nodes])
        print("JSON dumps: ", json.dumps(
            [node.__dict__() for node in reactflow_nodes]))

        for connection in connections:
            edge = Edge()
            edge.source = str(connection["node1Id"])
            edge.target = str(connection["node2Id"])
            edge.targetHandle = connection["node2Input"]
            edge.sourceHandle = connection["node1Output"]
            edge.id = f"{edge.source}[{edge.sourceHandle}]-{edge.target}[{edge.targetHandle}]"
            edges.append(edge)
        print("Edges: ", json.dumps([vars(edge) for edge in edges]))

#   {
#     id: "edge-1",
#     source: "0",
#     sourceHandle: "preview",
#     target: "1",
#     targetHandle: "in",
#     animated: true,
#     label: "preview",
#   },


#       {
#     id: "1",
#     type: "pipelineNode",
#     data: {
#       label: "Input Node",
#     },
#     position: { x: 250, y: 0 },
#   },


def main():
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(
        help="Action", required=True, dest="action")

    run_parser = subparsers.add_parser("run",
                                       help="Run your depthai program to create the corresponding pipeline graph")
    run_parser.add_argument('command', type=str,
                            help="The command with its arguments between ' or \" (ex: python script.py -i file)")
    run_parser.add_argument("-dnk", "--do_not_kill", action="store_true",
                            help="Don't terminate the command when the schema string has been retrieved")
    run_parser.add_argument("-var", "--use_variable_names", action="store_true",
                            help="Use the variable names from the python code to name the graph nodes")
    run_parser.add_argument("-p", "--pipeline_name", type=str, default="pipeline",
                            help="Name of the pipeline variable in the python code (default=%(default)s)")
    run_parser.add_argument('-v', '--verbose', action="store_true",
                            help="Show on the console the command output")

    from_file_parser = subparsers.add_parser("from_file",
                                             help="Create the pipeline graph by parsing a file containing the schema (log file generated with DEPTHAI_LEVEL=debug or Json file generated by pipeline.serializeToJSon())")
    from_file_parser.add_argument("schema_file",
                                  help="Path of the file containing the schema")

    load_parser = subparsers.add_parser(
        "load", help="Load a previously saved pipeline graph")
    load_parser.add_argument("json_file",
                             help="Path of the .json file")
    args = parser.parse_args()

    p = PipelineGraph()
    p.cmd_tool(args)

    # while True:
    #     p.update()
    #     time.sleep(0.001)


# Run as standalone tool
if __name__ == "__main__":
    main()
