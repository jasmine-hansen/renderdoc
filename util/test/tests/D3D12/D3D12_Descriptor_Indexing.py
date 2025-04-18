import rdtest
import renderdoc as rd


class D3D12_Descriptor_Indexing(rdtest.TestCase):
    demos_test_name = 'D3D12_Descriptor_Indexing'

    def check_compute(self, eventId):
        action = self.find_action("Dispatch", eventId)
        self.check(action is not None)
        self.controller.SetFrameEvent(action.eventId, False)

        pipe = self.controller.GetPipelineState()
        d3d12pipe = self.controller.GetD3D12PipelineState()

        rw = pipe.GetReadWriteResources(rd.ShaderStage.Compute)

        self.check_eq(len(rw), 1)
        self.check_eq(rw[0].access.index, 0)
        self.check_eq(rw[0].access.stage, rd.ShaderStage.Compute)
        self.check_eq(rw[0].access.type, rd.DescriptorType.ReadWriteBuffer)
        self.check_eq(rw[0].access.staticallyUnused, False)
        self.check_eq(rw[0].access.arrayElement, 15)
        # we don't check currently which one is the sampler heap
        self.check(rw[0].access.descriptorStore in d3d12pipe.descriptorHeaps)

        self.check_eq(len(pipe.GetReadOnlyResources(rd.ShaderStage.Compute)), 0)

        rw_used = pipe.GetReadWriteResources(rd.ShaderStage.Compute, True)

        # should get the same results for dynamic array indexing, the 'only used' is only for
        # statically unused or used bindings
        self.check(rw == rw_used)

    def check_capture(self):
        for sm in ["sm_5_1", "sm_6_0", "sm_6_6"]:
            base = self.find_action("Tests " + sm)
            if base == None:
                rdtest.log.print("Skipping test " + sm)
                continue
            self.check_compute(base.eventId)

            action = self.find_action("Draw", base.eventId)
            self.check(action is not None)
            self.controller.SetFrameEvent(action.eventId, False)

            pipe = self.controller.GetPipelineState()
            d3d12pipe = self.controller.GetD3D12PipelineState()

            # Check bindings:
            #   - buffer 8 in root range 0 should be statically used (single fixed declaration) for the parameters
            #     image 12 in root range 0 should also be statically used
            #   - images 19, 20, 21 in root range 1 should be used for the non-uniform index
            #     images 49 & 59 in root range 1 should be used for a second array in the same range
            #     image 60 in root range 1 should be used for a fixed index in an array
            #     image 99 and 103 in root range 1 should be used
            #
            # Currently D3D12 only reports descriptor category
            bind_info = {
                (rd.DescriptorCategory.ReadOnlyResource, 0): {
                    'loc': (0, 8),
                    'elems': [0],
                    'names': {0: ''}
                },
                (rd.DescriptorCategory.ReadOnlyResource, 1): {
                    'loc': (0, 12),
                    'elems': [0],
                    'names': {0: 'smiley'}
                },
                (rd.DescriptorCategory.ReadOnlyResource, 2): {
                    'loc': (1, 0),
                    'elems': [19, 20, 21],
                    'names': {19: 'another_smiley', 20: 'more_smileys???', 21: ''}
                },
                (rd.DescriptorCategory.ReadOnlyResource, 3): {
                    'loc': (1, 40),
                    'elems': [9, 19, 20],
                    'names': {9: '', 19: '', 20: ''}
                },
                (rd.DescriptorCategory.ReadOnlyResource, 4): {
                    'loc': (1, 80),
                    'elems': [19, 23],
                    'names': {19: '', 23: ''}
                },
                (rd.DescriptorCategory.Sampler, 1): {
                    'loc': (1, 0),
                    'elems': [19, 20, 21],
                    'names': {19: '', 20: '', 21: ''}
                },
            }

            ro = pipe.GetReadOnlyResources(rd.ShaderStage.Pixel)
            samp = pipe.GetSamplers(rd.ShaderStage.Pixel)
            rw = pipe.GetReadWriteResources(rd.ShaderStage.Pixel)

            self.check_eq(len(ro), 2 + 8)
            self.check_eq(len(samp), 1 + 3)
            self.check_eq(len(rw), 0)

            refl = pipe.GetShaderReflection(rd.ShaderStage.Pixel)

            for a in samp + ro:
                idx = (rd.CategoryForDescriptorType(a.access.type), a.access.index)
                if a.access.type == rd.DescriptorType.Sampler and a.access.index == 0:  # static sampler
                    # descriptor store should not be a heap, but we don't verify exactly where it comes from
                    self.check(a.access.descriptorStore not in d3d12pipe.descriptorHeaps)
                    continue

                heapName = "ResourceDescriptorHeap"
                if rd.IsReadOnlyDescriptor(a.access.type):
                    res = refl.readOnlyResources[a.access.index]
                elif rd.IsReadWriteDescriptor(a.access.type):
                    res = refl.readOnlyResources[a.access.index]
                else:
                    res = refl.samplers[a.access.index]
                    heapName = "SamplerDescriptorHeap"

                if idx not in bind_info.keys():
                    raise rdtest.TestFailureException(
                        "Accessed bind {} of type {} doesn't exist in expected list".format(
                            a.access.index, str(a.access.type)))

                if a.access.arrayElement not in bind_info[idx]['elems']:
                    raise rdtest.TestFailureException(
                        "Bind {} reports array element {} as used, which shouldn't be".format(
                            res.name, a.access.arrayElement))

                if (res.fixedBindSetOrSpace, res.fixedBindNumber) != bind_info[idx]['loc']:
                    raise rdtest.TestFailureException("Bind {} expected to be {} but is {}, {}".format(
                        res.name, bind_info[idx]['loc'], res.fixedBindSetOrSpace, res.fixedBindNumber))

                # On D3D12 the logical location is just an index into the heap. This test sets up all
                # descriptor tables at 0 so register = heap
                loc = self.controller.GetDescriptorLocations(a.access.descriptorStore,
                                                             [rd.DescriptorRange(a.access)])[0]
                if loc.fixedBindNumber != bind_info[idx]['loc'][1] + a.access.arrayElement:
                    raise rdtest.TestFailureException(
                        "Location {} not expected for {} at space,reg {} array element {}".format(
                            loc.fixedBindNumber, str(a.access.type), bind_info[idx]['loc'], a.access.arrayElement))
                
                expectedDescName = bind_info[idx]['names'][a.access.arrayElement]
                if expectedDescName == '':
                    expectedDescName = heapName

                expectedDescName = "{}[{}]".format(expectedDescName, bind_info[idx]['loc'][1] + a.access.arrayElement)

                if loc.logicalBindName != expectedDescName:
                    raise rdtest.TestFailureException(
                        "Location {} not the expected {} for space,reg {} array element {}".format(
                            loc.logicalBindName, expectedDescName, bind_info[idx]['loc'], a.access.arrayElement))

                bind_info[idx]['elems'].remove(a.access.arrayElement)

            rdtest.log.success("Dynamic usage is as expected for {}".format(sm))

        for sm in ["sm_6_6_heap"]:
            base = self.find_action("Tests " + sm)
            if base == None:
                rdtest.log.print("Skipping test " + sm)
                continue
            self.check_compute(base.eventId)

            action = self.find_action("Draw", base.eventId)
            self.check(action is not None)
            self.controller.SetFrameEvent(action.eventId, False)

            pipe = self.controller.GetPipelineState()

            # Check bindings:
            #   - CBV
            #   - Samplers
            #   - SRV resources
            #   - UAV resources
            bind_info = {
                rd.DescriptorCategory.ConstantBlock: [9],
                rd.DescriptorCategory.Sampler: [0, 1, 2, 19, 20, 21, 25],
                rd.DescriptorCategory.ReadOnlyResource: [8, 12, 19, 20, 21, 49, 59, 6, 99, 103, 156, 162],
                rd.DescriptorCategory.ReadWriteResource: [10],
            }

            ro = pipe.GetReadOnlyResources(rd.ShaderStage.Pixel)
            samp = pipe.GetSamplers(rd.ShaderStage.Pixel)
            rw = pipe.GetReadWriteResources(rd.ShaderStage.Pixel)

            # All accesses should come direct without a shader binding
            self.check(all([d.access.index == rd.DescriptorAccess.NoShaderBinding for d in ro]))
            self.check(all([d.access.index == rd.DescriptorAccess.NoShaderBinding for d in samp]))
            self.check(all([d.access.index == rd.DescriptorAccess.NoShaderBinding for d in rw]))
            # Check accesses are in the right lists
            self.check(
                all([rd.CategoryForDescriptorType(d.access.type) == rd.DescriptorCategory.ReadOnlyResource for d in ro
                    ]))
            self.check(all([rd.CategoryForDescriptorType(d.access.type) == rd.DescriptorCategory.Sampler for d in samp
                           ]))
            self.check(
                all([
                    rd.CategoryForDescriptorType(d.access.type) == rd.DescriptorCategory.ReadWriteResource for d in rw
                ]))
            # the "byte offsets" are descriptor indices and should match the expectation above
            self.check([d.access.byteOffset for d in rw] == sorted(bind_info[rd.DescriptorCategory.ReadWriteResource]))
            self.check([d.access.byteOffset for d in ro] == sorted(bind_info[rd.DescriptorCategory.ReadOnlyResource]))
            self.check([d.access.byteOffset for d in samp] == sorted(bind_info[rd.DescriptorCategory.Sampler]))
            
            descriptor_names = {
                12: 'smiley',
                19: 'another_smiley',
                20: 'more_smileys???',
                10: 'outUAV',
            }

            for a in ro + rw:
                loc = self.controller.GetDescriptorLocations(a.access.descriptorStore,
                                                             [rd.DescriptorRange(a.access)])[0]

                if loc.fixedBindNumber != a.access.byteOffset:
                    raise rdtest.TestFailureException("Bind {} not expected for space,reg {} array element {}".format(
                        loc.fixedBindNumber, a.access.byteOffset))

                if a.access.byteOffset in descriptor_names.keys():
                    name = descriptor_names[a.access.byteOffset]
                else:
                    name = "ResourceDescriptorHeap"

                if loc.logicalBindName != f"{name}[{a.access.byteOffset}]":
                    raise rdtest.TestFailureException(
                        f"Bind '{loc.logicalBindName}' is not the expected '{name}' for descriptor {a.access.byteOffset}")

            for a in samp:
                loc = self.controller.GetDescriptorLocations(a.access.descriptorStore,
                                                             [rd.DescriptorRange(a.access)])[0]

                if loc.fixedBindNumber != a.access.byteOffset:
                    raise rdtest.TestFailureException("Bind {} not expected for space,reg {} array element {}".format(
                        loc.fixedBindNumber, a.access.byteOffset))

                if loc.logicalBindName != "SamplerDescriptorHeap[{}]".format(a.access.byteOffset):
                    raise rdtest.TestFailureException(
                        "Bind {} not expected for descriptor access SamplerDescriptorHeap[{}]".format(
                            loc.logicalBindName, a.access.byteOffset))

            rdtest.log.success("Dynamic usage is as expected for {}".format(sm))
